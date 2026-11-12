package ua.pp.sdgen.app;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import androidx.activity.result.ActivityResult;
import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.BufferedInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@CapacitorPlugin(name = "OtaUpdater")
public class OtaUpdaterPlugin extends Plugin {

    private static final int CONNECT_TIMEOUT_MS = 15000;
    private static final int READ_TIMEOUT_MS = 60000;
    private static final Pattern APK_CODE_PATTERN = Pattern.compile("^sdgen-update-(\\d+)\\.apk$");

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private volatile String pendingApkPath = null;

    @PluginMethod
    public void getAppInfo(PluginCall call) {
        try {
            Context ctx = getContext();
            PackageManager pm = ctx.getPackageManager();
            PackageInfo info = pm.getPackageInfo(ctx.getPackageName(), 0);
            long versionCode = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P
                ? info.getLongVersionCode()
                : (long) info.versionCode;

            JSObject ret = new JSObject();
            ret.put("packageName", ctx.getPackageName());
            ret.put("versionName", info.versionName != null ? info.versionName : "");
            ret.put("versionCode", versionCode);
            ret.put("canInstallPackages", canInstallPackages());
            call.resolve(ret);
        } catch (Exception e) {
            call.reject("Не вдалося отримати версію додатка: " + e.getMessage(), e);
        }
    }

    @PluginMethod
    public void cleanupDownloadedUpdates(PluginCall call) {
        try {
            long currentCode = getCurrentVersionCode();
            File otaDir = new File(getContext().getCacheDir(), "ota");
            int removed = 0;
            if (otaDir.exists() && otaDir.isDirectory()) {
                File[] files = otaDir.listFiles();
                if (files != null) {
                    for (File f : files) {
                        String name = f.getName();
                        if (name.endsWith(".part")) {
                            if (f.delete()) removed++;
                            continue;
                        }
                        Matcher m = APK_CODE_PATTERN.matcher(name);
                        if (m.matches()) {
                            long fileCode = Long.parseLong(m.group(1));
                            if (fileCode <= currentCode && f.delete()) {
                                removed++;
                            }
                        }
                    }
                }
            }
            JSObject ret = new JSObject();
            ret.put("removed", removed);
            call.resolve(ret);
        } catch (Exception e) {
            call.reject("Помилка очищення кешу OTA: " + e.getMessage(), e);
        }
    }

    @PluginMethod
    public void downloadAndInstall(PluginCall call) {
        String downloadUrl = call.getString("url");
        String expectedSha256 = call.getString("sha256", "");
        long targetCode = call.getInt("versionCode", 0);

        if (downloadUrl == null || (!downloadUrl.startsWith("https://") && !downloadUrl.startsWith("http://"))) {
            call.reject("Некоректна URL-адреса завантаження APK.");
            return;
        }
        if (targetCode <= 0) {
            call.reject("Некоректний versionCode релізу.");
            return;
        }

        final String normalizedExpectedSha = expectedSha256 != null
            ? expectedSha256.trim().toLowerCase(Locale.ROOT)
            : "";

        executor.execute(() -> {
            File tmpFile = null;
            try {
                File otaDir = new File(getContext().getCacheDir(), "ota");
                if (!otaDir.exists() && !otaDir.mkdirs()) {
                    throw new IllegalStateException("Не вдалося створити директорію кешу OTA.");
                }

                File targetFile = new File(otaDir, "sdgen-update-" + targetCode + ".apk");
                if (targetFile.exists() && !normalizedExpectedSha.isEmpty()) {
                    String cachedSha = computeFileSha256(targetFile);
                    if (normalizedExpectedSha.equals(cachedSha) && verifyApkPackage(targetFile)) {
                        emitProgress(100, targetFile.length(), targetFile.length());
                        proceedWithInstall(call, targetFile);
                        return;
                    }
                    //noinspection ResultOfMethodCallIgnored
                    targetFile.delete();
                }

                tmpFile = new File(otaDir, "sdgen-update-" + targetCode + ".apk.part");
                if (tmpFile.exists()) {
                    //noinspection ResultOfMethodCallIgnored
                    tmpFile.delete();
                }

                URL url = new URL(downloadUrl);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setInstanceFollowRedirects(true);
                conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
                conn.setReadTimeout(READ_TIMEOUT_MS);
                conn.setRequestProperty("Cache-Control", "no-cache");

                int statusCode = conn.getResponseCode();
                if (statusCode != HttpURLConnection.HTTP_OK) {
                    throw new IllegalStateException("Сервер повернув HTTP " + statusCode);
                }

                long totalBytes = conn.getContentLengthLong();
                long downloadedBytes = 0;
                int lastPercent = -1;
                MessageDigest digest = MessageDigest.getInstance("SHA-256");

                try (
                    InputStream in = new BufferedInputStream(conn.getInputStream());
                    FileOutputStream out = new FileOutputStream(tmpFile)
                ) {
                    byte[] buffer = new byte[32 * 1024];
                    int read;
                    while ((read = in.read(buffer)) != -1) {
                        out.write(buffer, 0, read);
                        digest.update(buffer, 0, read);
                        downloadedBytes += read;

                        if (totalBytes > 0) {
                            int pct = (int) Math.min(99, (downloadedBytes * 100L) / totalBytes);
                            if (pct >= lastPercent + 2 || pct == 0) {
                                lastPercent = pct;
                                emitProgress(pct, downloadedBytes, totalBytes);
                            }
                        } else if (downloadedBytes % (256 * 1024) < 32 * 1024) {
                            emitProgress(-1, downloadedBytes, -1);
                        }
                    }
                    out.flush();
                } finally {
                    conn.disconnect();
                }

                String actualSha = bytesToHex(digest.digest());
                if (!normalizedExpectedSha.isEmpty() && !normalizedExpectedSha.equals(actualSha)) {
                    throw new SecurityException("Контрольна сума SHA-256 не співпадає. Файл пошкоджено.");
                }

                if (!tmpFile.renameTo(targetFile)) {
                    throw new IllegalStateException("Не вдалося зберегти завантажений APK.");
                }

                if (!verifyApkPackage(targetFile)) {
                    //noinspection ResultOfMethodCallIgnored
                    targetFile.delete();
                    throw new SecurityException("Завантажений файл не відповідає пакету " + getContext().getPackageName());
                }

                emitProgress(100, downloadedBytes, totalBytes > 0 ? totalBytes : downloadedBytes);
                proceedWithInstall(call, targetFile);
            } catch (Exception e) {
                if (tmpFile != null && tmpFile.exists()) {
                    //noinspection ResultOfMethodCallIgnored
                    tmpFile.delete();
                }
                call.reject("Не вдалося завантажити оновлення: " + e.getMessage(), e);
            }
        });
    }

    private void proceedWithInstall(PluginCall call, File apkFile) {
        getBridge().executeOnMainThread(() -> {
            try {
                pendingApkPath = apkFile.getAbsolutePath();
                if (!canInstallPackages()) {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        Intent intent = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES);
                        intent.setData(Uri.parse("package:" + getContext().getPackageName()));
                        startActivityForResult(call, intent, "handleInstallPermissionResult");
                        return;
                    }
                }
                launchApkInstaller(apkFile);
                JSObject ret = new JSObject();
                ret.put("status", "installer_launched");
                call.resolve(ret);
            } catch (Exception e) {
                call.reject("Помилка запуску інсталятора: " + e.getMessage(), e);
            }
        });
    }

    @ActivityCallback
    private void handleInstallPermissionResult(PluginCall call, ActivityResult result) {
        if (call == null) {
            return;
        }
        try {
            if (!canInstallPackages()) {
                JSObject ret = new JSObject();
                ret.put("status", "permission_required");
                call.resolve(ret);
                return;
            }
            if (pendingApkPath == null) {
                call.reject("Шлях до завантаженого APK втрачено. Спробуйте ще раз.");
                return;
            }
            File apkFile = new File(pendingApkPath);
            if (!apkFile.exists()) {
                call.reject("Файл оновлення відсутній. Повторіть завантаження.");
                return;
            }
            launchApkInstaller(apkFile);
            JSObject ret = new JSObject();
            ret.put("status", "installer_launched");
            call.resolve(ret);
        } catch (Exception e) {
            call.reject("Не вдалося завершити встановлення: " + e.getMessage(), e);
        }
    }

    private void launchApkInstaller(File apkFile) {
        Context ctx = getContext();
        Uri apkUri = FileProvider.getUriForFile(ctx, ctx.getPackageName() + ".fileprovider", apkFile);
        Intent intent = new Intent(Intent.ACTION_VIEW);
        intent.setDataAndType(apkUri, "application/vnd.android.package-archive");
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        ctx.startActivity(intent);
    }

    private boolean canInstallPackages() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            return getContext().getPackageManager().canRequestPackageInstalls();
        }
        return true;
    }

    private long getCurrentVersionCode() throws PackageManager.NameNotFoundException {
        PackageInfo info = getContext().getPackageManager().getPackageInfo(getContext().getPackageName(), 0);
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.P
            ? info.getLongVersionCode()
            : (long) info.versionCode;
    }

    @SuppressWarnings("deprecation")
    private boolean verifyApkPackage(File apkFile) {
        PackageInfo archiveInfo = getContext().getPackageManager().getPackageArchiveInfo(apkFile.getAbsolutePath(), 0);
        return archiveInfo != null && getContext().getPackageName().equals(archiveInfo.packageName);
    }

    private void emitProgress(int percent, long downloadedBytes, long totalBytes) {
        JSObject data = new JSObject();
        data.put("percent", percent);
        data.put("downloadedBytes", downloadedBytes);
        data.put("totalBytes", totalBytes);
        notifyListeners("otaDownloadProgress", data);
    }

    private String computeFileSha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream in = new BufferedInputStream(new FileInputStream(file))) {
            byte[] buf = new byte[32 * 1024];
            int r;
            while ((r = in.read(buf)) != -1) {
                digest.update(buf, 0, r);
            }
        }
        return bytesToHex(digest.digest());
    }

    private static String bytesToHex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            sb.append(String.format(Locale.ROOT, "%02x", b & 0xff));
        }
        return sb.toString();
    }
}
