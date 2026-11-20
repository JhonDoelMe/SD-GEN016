package ua.pp.sdgen.app;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import com.getcapacitor.Bridge;

import java.io.BufferedInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Manages Capacitor Web-OTA bundles stored in internal app storage with
 * SHA-256 pre-verification, Zip-Slip protection, and automatic crash/timeout rollback.
 */
public final class WebOtaManager {

    private static final String TAG = "SdgenWebOta";
    private static final String PREFS_NAME = "SdgenWebOtaPrefs";
    private static final String CAP_PREFS_NAME = com.getcapacitor.plugin.WebView.WEBVIEW_PREFS_NAME;
    private static final String CAP_SERVER_PATH = com.getcapacitor.plugin.WebView.CAP_SERVER_PATH;

    private static final String KEY_LAST_APK_CODE = "last_apk_version_code";
    private static final String KEY_ACTIVE_PATH = "active_bundle_path";
    private static final String KEY_ACTIVE_BUILD = "active_web_build";
    private static final String KEY_ACTIVE_VERSION = "active_web_version";

    private static final String KEY_PENDING_PATH = "pending_bundle_path";
    private static final String KEY_PENDING_BUILD = "pending_web_build";
    private static final String KEY_PENDING_VERSION = "pending_web_version";
    private static final String KEY_PENDING_ATTEMPTS = "pending_boot_attempts";

    private static final String KEY_CONFIRMED_PATH = "confirmed_bundle_path";
    private static final String KEY_CONFIRMED_BUILD = "confirmed_web_build";
    private static final String KEY_CONFIRMED_VERSION = "confirmed_web_version";

    private static final long MAX_UNCOMPRESSED_BYTES = 120L * 1024L * 1024L;
    private static final int MAX_ZIP_ENTRIES = 5000;

    private WebOtaManager() {}

    public static final class WebOtaState {
        public final long nativeVersionCode;
        public final String nativeVersionName;
        public final long effectiveWebBuild;
        public final String effectiveVersionName;
        public final boolean isWebOtaActive;
        public final boolean hasPendingBoot;

        WebOtaState(
            long nativeVersionCode,
            String nativeVersionName,
            long effectiveWebBuild,
            String effectiveVersionName,
            boolean isWebOtaActive,
            boolean hasPendingBoot
        ) {
            this.nativeVersionCode = nativeVersionCode;
            this.nativeVersionName = nativeVersionName;
            this.effectiveWebBuild = effectiveWebBuild;
            this.effectiveVersionName = effectiveVersionName;
            this.isWebOtaActive = isWebOtaActive;
            this.hasPendingBoot = hasPendingBoot;
        }
    }

    public static long getNativeVersionCode(Context ctx) throws PackageManager.NameNotFoundException {
        PackageInfo info = ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0);
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.P
            ? info.getLongVersionCode()
            : (long) info.versionCode;
    }

    public static String getNativeVersionName(Context ctx) throws PackageManager.NameNotFoundException {
        PackageInfo info = ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0);
        return info.versionName != null ? info.versionName : "";
    }

    public static File getWebOtaRoot(Context ctx) {
        return new File(ctx.getFilesDir(), "web_ota");
    }

    /**
     * Runs BEFORE BridgeActivity.onCreate() so Capacitor sees the validated or rolled-back path.
     */
    public static synchronized boolean prepareBeforeBridgeCreate(Context ctx) {
        SharedPreferences prefs = ctx.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        SharedPreferences capPrefs = ctx.getSharedPreferences(CAP_PREFS_NAME, Activity.MODE_PRIVATE);

        long nativeCode = 0;
        try {
            nativeCode = getNativeVersionCode(ctx);
        } catch (Exception e) {
            Log.w(TAG, "Cannot read PackageInfo: " + e.getMessage());
        }

        long lastApkCode = prefs.getLong(KEY_LAST_APK_CODE, -1L);
        if (nativeCode > 0 && lastApkCode != nativeCode) {
            Log.i(TAG, "Native APK binary changed (" + lastApkCode + " -> " + nativeCode + "), resetting Web-OTA storage.");
            deleteRecursively(getWebOtaRoot(ctx));
            prefs.edit()
                .clear()
                .putLong(KEY_LAST_APK_CODE, nativeCode)
                .apply();
            capPrefs.edit().putString(CAP_SERVER_PATH, "").apply();
            return false;
        }

        String pendingPath = prefs.getString(KEY_PENDING_PATH, "");
        if (pendingPath != null && !pendingPath.isEmpty()) {
            int attempts = prefs.getInt(KEY_PENDING_ATTEMPTS, 0);
            File pendingDir = new File(pendingPath);
            if (attempts >= 1 || !isBundleDirValid(pendingDir)) {
                Log.w(TAG, "Web-OTA pending bundle failed boot check (attempts=" + attempts + "), rolling back.");
                rollbackToConfirmedLocked(ctx, prefs, capPrefs);
                return false;
            }
            prefs.edit().putInt(KEY_PENDING_ATTEMPTS, attempts + 1).apply();
            capPrefs.edit().putString(CAP_SERVER_PATH, pendingDir.getAbsolutePath()).apply();
            return true;
        }

        String confirmedPath = prefs.getString(KEY_CONFIRMED_PATH, "");
        long confirmedBuild = prefs.getLong(KEY_CONFIRMED_BUILD, 0L);
        if (confirmedPath != null && !confirmedPath.isEmpty()) {
            File confirmedDir = new File(confirmedPath);
            if (confirmedBuild > nativeCode && isBundleDirValid(confirmedDir)) {
                capPrefs.edit().putString(CAP_SERVER_PATH, confirmedDir.getAbsolutePath()).apply();
                prefs.edit()
                    .putString(KEY_ACTIVE_PATH, confirmedDir.getAbsolutePath())
                    .putLong(KEY_ACTIVE_BUILD, confirmedBuild)
                    .putString(KEY_ACTIVE_VERSION, prefs.getString(KEY_CONFIRMED_VERSION, ""))
                    .apply();
            } else {
                Log.w(TAG, "Confirmed Web-OTA bundle is stale or invalid, reverting to bundled APK assets.");
                clearAllBundlePrefs(prefs, capPrefs, nativeCode);
            }
        } else {
            String capPath = capPrefs.getString(CAP_SERVER_PATH, "");
            if (capPath != null && !capPath.isEmpty()) {
                capPrefs.edit().putString(CAP_SERVER_PATH, "").apply();
            }
        }
        return false;
    }

    public static void scheduleRollbackWatchdog(Context ctx, Bridge bridge) {
        final Context appCtx = ctx.getApplicationContext();
        new Handler(Looper.getMainLooper()).postDelayed(
            () -> rollbackIfPendingOnTimeout(appCtx, bridge),
            15000L
        );
    }

    public static synchronized void rollbackIfPendingOnTimeout(Context ctx, Bridge bridge) {
        SharedPreferences prefs = ctx.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        String pendingPath = prefs.getString(KEY_PENDING_PATH, "");
        if (pendingPath == null || pendingPath.isEmpty()) {
            return;
        }
        Log.w(TAG, "Web-OTA confirmation timeout reached, auto-rolling back bundle: " + pendingPath);
        SharedPreferences capPrefs = ctx.getSharedPreferences(CAP_PREFS_NAME, Activity.MODE_PRIVATE);
        String targetPath = rollbackToConfirmedLocked(ctx, prefs, capPrefs);
        if (bridge != null) {
            if (targetPath != null && !targetPath.isEmpty()) {
                bridge.setServerBasePath(targetPath);
            } else {
                bridge.setServerAssetPath("public");
            }
        }
    }

    public static synchronized WebOtaState confirmBundleBoot(Context ctx) {
        SharedPreferences prefs = ctx.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        String pendingPath = prefs.getString(KEY_PENDING_PATH, "");
        if (pendingPath != null && !pendingPath.isEmpty()) {
            File pendingDir = new File(pendingPath);
            long pendingBuild = prefs.getLong(KEY_PENDING_BUILD, 0L);
            String pendingVer = prefs.getString(KEY_PENDING_VERSION, "");
            if (isBundleDirValid(pendingDir) && pendingBuild > 0L) {
                prefs.edit()
                    .putString(KEY_CONFIRMED_PATH, pendingDir.getAbsolutePath())
                    .putLong(KEY_CONFIRMED_BUILD, pendingBuild)
                    .putString(KEY_CONFIRMED_VERSION, pendingVer)
                    .putString(KEY_ACTIVE_PATH, pendingDir.getAbsolutePath())
                    .putLong(KEY_ACTIVE_BUILD, pendingBuild)
                    .putString(KEY_ACTIVE_VERSION, pendingVer)
                    .remove(KEY_PENDING_PATH)
                    .remove(KEY_PENDING_BUILD)
                    .remove(KEY_PENDING_VERSION)
                    .putInt(KEY_PENDING_ATTEMPTS, 0)
                    .apply();
                pruneInactiveBundleDirs(ctx, pendingDir.getAbsolutePath(), null);
            }
        }
        return getState(ctx);
    }

    public static synchronized String stageAndActivateBundle(
        Context ctx,
        Bridge bridge,
        File zipFile,
        long webBuild,
        String versionName
    ) throws IOException {
        File root = getWebOtaRoot(ctx);
        if (!root.exists() && !root.mkdirs()) {
            throw new IOException("Не вдалося створити директорію Web-OTA.");
        }

        File tmpDir = new File(root, "bundle-" + webBuild + ".tmp-" + System.currentTimeMillis());
        File finalDir = new File(root, "bundle-" + webBuild);
        try {
            unzipSafe(zipFile, tmpDir);
            if (!isBundleDirValid(tmpDir)) {
                throw new IOException("Розпакований Web-бандл не містить index.html або frontend/js/ota-updater.js.");
            }
            if (finalDir.exists()) {
                deleteRecursively(finalDir);
            }
            if (!tmpDir.renameTo(finalDir)) {
                throw new IOException("Не вдалося активувати директорію Web-бандлу.");
            }

            SharedPreferences prefs = ctx.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
            SharedPreferences capPrefs = ctx.getSharedPreferences(CAP_PREFS_NAME, Activity.MODE_PRIVATE);

            prefs.edit()
                .putString(KEY_PENDING_PATH, finalDir.getAbsolutePath())
                .putLong(KEY_PENDING_BUILD, webBuild)
                .putString(KEY_PENDING_VERSION, versionName != null ? versionName : "")
                .putInt(KEY_PENDING_ATTEMPTS, 0)
                .putString(KEY_ACTIVE_PATH, finalDir.getAbsolutePath())
                .putLong(KEY_ACTIVE_BUILD, webBuild)
                .putString(KEY_ACTIVE_VERSION, versionName != null ? versionName : "")
                .apply();
            capPrefs.edit().putString(CAP_SERVER_PATH, finalDir.getAbsolutePath()).apply();

            String confirmedPath = prefs.getString(KEY_CONFIRMED_PATH, "");
            pruneInactiveBundleDirs(ctx, finalDir.getAbsolutePath(), confirmedPath);

            if (bridge != null) {
                bridge.executeOnMainThread(() -> bridge.setServerBasePath(finalDir.getAbsolutePath()));
            }
            return finalDir.getAbsolutePath();
        } catch (Exception e) {
            deleteRecursively(tmpDir);
            if (e instanceof IOException) {
                throw (IOException) e;
            }
            throw new IOException(e.getMessage(), e);
        }
    }

    public static synchronized WebOtaState getState(Context ctx) {
        long nativeCode = 0;
        String nativeVer = "";
        try {
            nativeCode = getNativeVersionCode(ctx);
            nativeVer = getNativeVersionName(ctx);
        } catch (Exception ignored) {}

        SharedPreferences prefs = ctx.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        SharedPreferences capPrefs = ctx.getSharedPreferences(CAP_PREFS_NAME, Activity.MODE_PRIVATE);
        String capPath = capPrefs.getString(CAP_SERVER_PATH, "");

        long activeBuild = prefs.getLong(KEY_ACTIVE_BUILD, 0L);
        String activeVer = prefs.getString(KEY_ACTIVE_VERSION, "");
        String pendingPath = prefs.getString(KEY_PENDING_PATH, "");
        boolean hasPending = pendingPath != null && !pendingPath.isEmpty();

        boolean webActive = (capPath != null && !capPath.isEmpty() && activeBuild > nativeCode && isBundleDirValid(new File(capPath)));
        long effectiveBuild = webActive ? activeBuild : nativeCode;
        String effectiveVer = (webActive && activeVer != null && !activeVer.isEmpty()) ? activeVer : nativeVer;

        return new WebOtaState(nativeCode, nativeVer, effectiveBuild, effectiveVer, webActive, hasPending);
    }

    public static int cleanupTemporaryDirs(Context ctx) {
        int removed = 0;
        File root = getWebOtaRoot(ctx);
        if (!root.exists() || !root.isDirectory()) {
            return 0;
        }
        SharedPreferences prefs = ctx.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        String activePath = prefs.getString(KEY_ACTIVE_PATH, "");
        String confirmedPath = prefs.getString(KEY_CONFIRMED_PATH, "");
        String pendingPath = prefs.getString(KEY_PENDING_PATH, "");

        File[] children = root.listFiles();
        if (children == null) {
            return 0;
        }
        for (File f : children) {
            String p = f.getAbsolutePath();
            if (p.equals(activePath) || p.equals(confirmedPath) || p.equals(pendingPath)) {
                continue;
            }
            if (deleteRecursively(f)) {
                removed++;
            }
        }
        return removed;
    }

    private static String rollbackToConfirmedLocked(Context ctx, SharedPreferences prefs, SharedPreferences capPrefs) {
        String failedPending = prefs.getString(KEY_PENDING_PATH, "");
        String confirmedPath = prefs.getString(KEY_CONFIRMED_PATH, "");
        long confirmedBuild = prefs.getLong(KEY_CONFIRMED_BUILD, 0L);
        String confirmedVer = prefs.getString(KEY_CONFIRMED_VERSION, "");

        long nativeCode = 0;
        try {
            nativeCode = getNativeVersionCode(ctx);
        } catch (Exception ignored) {}

        String fallbackPath = "";
        if (confirmedPath != null && !confirmedPath.isEmpty() && confirmedBuild > nativeCode && isBundleDirValid(new File(confirmedPath))) {
            fallbackPath = confirmedPath;
            prefs.edit()
                .putString(KEY_ACTIVE_PATH, confirmedPath)
                .putLong(KEY_ACTIVE_BUILD, confirmedBuild)
                .putString(KEY_ACTIVE_VERSION, confirmedVer)
                .remove(KEY_PENDING_PATH)
                .remove(KEY_PENDING_BUILD)
                .remove(KEY_PENDING_VERSION)
                .putInt(KEY_PENDING_ATTEMPTS, 0)
                .apply();
        } else {
            prefs.edit()
                .remove(KEY_ACTIVE_PATH)
                .remove(KEY_ACTIVE_BUILD)
                .remove(KEY_ACTIVE_VERSION)
                .remove(KEY_CONFIRMED_PATH)
                .remove(KEY_CONFIRMED_BUILD)
                .remove(KEY_CONFIRMED_VERSION)
                .remove(KEY_PENDING_PATH)
                .remove(KEY_PENDING_BUILD)
                .remove(KEY_PENDING_VERSION)
                .putInt(KEY_PENDING_ATTEMPTS, 0)
                .apply();
        }
        capPrefs.edit().putString(CAP_SERVER_PATH, fallbackPath).apply();

        if (failedPending != null && !failedPending.isEmpty() && !failedPending.equals(fallbackPath)) {
            deleteRecursively(new File(failedPending));
        }
        return fallbackPath;
    }

    private static void clearAllBundlePrefs(SharedPreferences prefs, SharedPreferences capPrefs, long nativeCode) {
        prefs.edit()
            .clear()
            .putLong(KEY_LAST_APK_CODE, nativeCode)
            .apply();
        capPrefs.edit().putString(CAP_SERVER_PATH, "").apply();
    }

    private static boolean isBundleDirValid(File dir) {
        if (dir == null || !dir.isDirectory()) {
            return false;
        }
        return new File(dir, "index.html").isFile()
            && new File(dir, "frontend/js/ota-updater.js").isFile();
    }

    private static void pruneInactiveBundleDirs(Context ctx, String keepPathA, String keepPathB) {
        File root = getWebOtaRoot(ctx);
        File[] files = root.listFiles();
        if (files == null) return;
        for (File f : files) {
            String abs = f.getAbsolutePath();
            if (abs.equals(keepPathA) || (keepPathB != null && abs.equals(keepPathB))) {
                continue;
            }
            deleteRecursively(f);
        }
    }

    private static void unzipSafe(File zipFile, File targetDir) throws IOException {
        if (!targetDir.exists() && !targetDir.mkdirs()) {
            throw new IOException("Не вдалося створити тимчасову директорію розпакування.");
        }
        String canonicalRoot = targetDir.getCanonicalPath() + File.separator;
        long totalExtracted = 0L;
        int entryCount = 0;
        byte[] buffer = new byte[32 * 1024];

        try (ZipInputStream zis = new ZipInputStream(new BufferedInputStream(new FileInputStream(zipFile)))) {
            ZipEntry entry;
            while ((entry = zis.getNextEntry()) != null) {
                entryCount++;
                if (entryCount > MAX_ZIP_ENTRIES) {
                    throw new IOException("Перевищено ліміт кількості файлів у Web-бандлі.");
                }
                String name = entry.getName();
                if (name == null || name.isEmpty()) {
                    continue;
                }
                File outFile = new File(targetDir, name);
                String canonicalOut = outFile.getCanonicalPath();
                if (!canonicalOut.startsWith(canonicalRoot)) {
                    throw new IOException("Виявлено небезпечний шлях у ZIP-архіві: " + name);
                }
                if (entry.isDirectory()) {
                    if (!outFile.exists() && !outFile.mkdirs()) {
                        throw new IOException("Не вдалося створити каталог: " + name);
                    }
                    continue;
                }
                File parent = outFile.getParentFile();
                if (parent != null && !parent.exists() && !parent.mkdirs()) {
                    throw new IOException("Не вдалося створити батьківський каталог: " + name);
                }
                try (FileOutputStream fos = new FileOutputStream(outFile)) {
                    int read;
                    while ((read = zis.read(buffer)) != -1) {
                        totalExtracted += read;
                        if (totalExtracted > MAX_UNCOMPRESSED_BYTES) {
                            throw new IOException("Розпакований Web-бандл перевищує допустимий розмір.");
                        }
                        fos.write(buffer, 0, read);
                    }
                }
                zis.closeEntry();
            }
        }
    }

    private static boolean deleteRecursively(File target) {
        if (target == null || !target.exists()) {
            return false;
        }
        if (target.isDirectory()) {
            File[] children = target.listFiles();
            if (children != null) {
                for (File c : children) {
                    deleteRecursively(c);
                }
            }
        }
        return target.delete();
    }
}
