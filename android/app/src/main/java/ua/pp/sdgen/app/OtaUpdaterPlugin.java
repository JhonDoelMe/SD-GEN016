package ua.pp.sdgen.app;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;

import com.getcapacitor.Bridge;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.BufferedInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Pattern;

/**
 * Safe Web-OTA updater plugin for Capacitor.
 * Downloads signed-by-hash Web-OTA ZIP bundles over HTTPS and applies them via
 * Capacitor's setServerBasePath without requiring REQUEST_INSTALL_PACKAGES.
 */
@CapacitorPlugin(name = "OtaUpdater")
public class OtaUpdaterPlugin extends Plugin {

    private static final int CONNECT_TIMEOUT_MS = 15000;
    private static final int READ_TIMEOUT_MS = 60000;
    private static final long MAX_WEB_ZIP_BYTES = 50L * 1024L * 1024L;
    private static final Pattern SHA256_PATTERN = Pattern.compile("^[0-9a-f]{64}$");

    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    @PluginMethod
    public void getAppInfo(PluginCall call) {
        try {
            Context ctx = getContext();
            WebOtaManager.WebOtaState state = WebOtaManager.getState(ctx);

            JSObject ret = new JSObject();
            ret.put("packageName", ctx.getPackageName());
            ret.put("versionName", state.effectiveVersionName);
            ret.put("versionCode", state.nativeVersionCode);
            ret.put("nativeVersionCode", state.nativeVersionCode);
            ret.put("nativeVersionName", state.nativeVersionName);
            ret.put("webBuild", state.effectiveWebBuild);
            ret.put("isWebOtaActive", state.isWebOtaActive);
            ret.put("hasPendingBoot", state.hasPendingBoot);
            call.resolve(ret);
        } catch (Exception e) {
            call.reject("Не вдалося отримати версію додатка: " + e.getMessage(), e);
        }
    }

    @PluginMethod
    public void confirmWebBundle(PluginCall call) {
        try {
            WebOtaManager.WebOtaState state = WebOtaManager.confirmBundleBoot(getContext());
            JSObject ret = new JSObject();
            ret.put("confirmed", true);
            ret.put("webBuild", state.effectiveWebBuild);
            ret.put("versionName", state.effectiveVersionName);
            ret.put("isWebOtaActive", state.isWebOtaActive);
            call.resolve(ret);
        } catch (Exception e) {
            call.reject("Не вдалося підтвердити Web-OTA бандл: " + e.getMessage(), e);
        }
    }

    @PluginMethod
    public void cleanupDownloadedUpdates(PluginCall call) {
        try {
            int removed = WebOtaManager.cleanupTemporaryDirs(getContext());

            // Clean legacy cacheDir/ota APK files from pre-5.8.0 versions
            File legacyOtaDir = new File(getContext().getCacheDir(), "ota");
            if (legacyOtaDir.exists() && legacyOtaDir.isDirectory()) {
                File[] files = legacyOtaDir.listFiles();
                if (files != null) {
                    for (File f : files) {
                        if (f.delete()) {
                            removed++;
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
    public void downloadAndApplyWebBundle(PluginCall call) {
        String downloadUrl = call.getString("url");
        String expectedSha256 = call.getString("sha256", "");
        String versionName = call.getString("versionName", "");
        long targetWebBuild = call.getInt("webBuild", 0);

        final URL parsedDownloadUrl = validateHttpsUrl(downloadUrl);
        if (parsedDownloadUrl == null) {
            call.reject("Небезпечна або некоректна URL-адреса завантаження Web-оновлення (потрібен HTTPS).");
            return;
        }

        if (targetWebBuild <= 0) {
            call.reject("Некоректний webBuild релізу.");
            return;
        }

        final String normalizedExpectedSha = expectedSha256 != null
            ? expectedSha256.trim().toLowerCase(Locale.ROOT)
            : "";
        if (!SHA256_PATTERN.matcher(normalizedExpectedSha).matches()) {
            call.reject("Відсутня або некоректна контрольна сума SHA-256 Web-бандлу.");
            return;
        }

        executor.execute(() -> {
            File tmpZip = null;
            try {
                long nativeCode = WebOtaManager.getNativeVersionCode(getContext());
                if (targetWebBuild <= nativeCode) {
                    throw new IllegalStateException("Вбудована версія додатка вже новіша або дорівнює обраному Web-бандлу.");
                }

                File otaCache = new File(getContext().getCacheDir(), "web_ota_dl");
                if (!otaCache.exists() && !otaCache.mkdirs()) {
                    throw new IllegalStateException("Не вдалося створити тимчасову директорію кешу Web-OTA.");
                }
                tmpZip = new File(otaCache, "bundle-" + targetWebBuild + "-" + System.currentTimeMillis() + ".zip.part");

                HttpURLConnection conn = (HttpURLConnection) parsedDownloadUrl.openConnection();
                conn.setInstanceFollowRedirects(false);
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
                    FileOutputStream out = new FileOutputStream(tmpZip)
                ) {
                    byte[] buffer = new byte[32 * 1024];
                    int read;
                    while ((read = in.read(buffer)) != -1) {
                        downloadedBytes += read;
                        if (downloadedBytes > MAX_WEB_ZIP_BYTES) {
                            throw new SecurityException("Розмір Web-OTA бандлу перевищує допустимий ліміт.");
                        }
                        out.write(buffer, 0, read);
                        digest.update(buffer, 0, read);

                        if (totalBytes > 0) {
                            int pct = (int) Math.min(95, (downloadedBytes * 95L) / totalBytes);
                            if (pct >= lastPercent + 3 || pct == 0) {
                                lastPercent = pct;
                                emitProgress(pct, downloadedBytes, totalBytes);
                            }
                        } else if (downloadedBytes % (128 * 1024) < 32 * 1024) {
                            emitProgress(-1, downloadedBytes, -1);
                        }
                    }
                    out.flush();
                } finally {
                    conn.disconnect();
                }

                String actualSha = bytesToHex(digest.digest());
                if (!normalizedExpectedSha.equals(actualSha)) {
                    throw new SecurityException("Контрольна сума SHA-256 Web-бандлу не збігається.");
                }

                emitProgress(98, downloadedBytes, totalBytes > 0 ? totalBytes : downloadedBytes);

                final Bridge bridge = getBridge();
                final String activeBundlePath = WebOtaManager.stageAndActivateBundle(
                    getContext(),
                    null,
                    tmpZip,
                    targetWebBuild,
                    versionName
                );
                emitProgress(100, downloadedBytes, totalBytes > 0 ? totalBytes : downloadedBytes);

                JSObject ret = new JSObject();
                ret.put("status", "applied");
                ret.put("webBuild", targetWebBuild);
                ret.put("versionName", versionName);
                call.resolve(ret);

                final Context appCtx = getContext().getApplicationContext();
                new Handler(Looper.getMainLooper()).postDelayed(() -> {
                    WebOtaManager.scheduleRollbackWatchdog(appCtx, bridge);
                    if (bridge != null) {
                        bridge.setServerBasePath(activeBundlePath);
                    }
                }, 150L);
            } catch (Exception e) {
                call.reject("Не вдалося завантажити Web-оновлення: " + e.getMessage(), e);
            } finally {
                if (tmpZip != null && tmpZip.exists()) {
                    //noinspection ResultOfMethodCallIgnored
                    tmpZip.delete();
                }
            }
        });
    }

    @PluginMethod
    public void openBrowserUrl(PluginCall call) {
        String rawUrl = call.getString("url");
        URL parsed = validateHttpsUrl(rawUrl);
        if (parsed == null) {
            call.reject("Некоректне або небезпечне посилання (потрібен HTTPS).");
            return;
        }
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(parsed.toString()));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
            JSObject ret = new JSObject();
            ret.put("opened", true);
            call.resolve(ret);
        } catch (Exception e) {
            call.reject("Не вдалося відкрити браузер: " + e.getMessage(), e);
        }
    }

    private URL validateHttpsUrl(String rawUrl) {
        if (rawUrl == null || !rawUrl.startsWith("https://")) {
            return null;
        }
        try {
            URL parsed = new URL(rawUrl);
            String host = parsed.getHost() != null
                ? parsed.getHost().trim().toLowerCase(Locale.ROOT)
                : "";
            if (host.isEmpty() || "localhost".equals(host) || host.startsWith("127.") || "169.254.169.254".equals(host)) {
                return null;
            }
            return parsed;
        } catch (Exception e) {
            return null;
        }
    }

    private void emitProgress(int percent, long downloadedBytes, long totalBytes) {
        JSObject data = new JSObject();
        data.put("percent", percent);
        data.put("downloadedBytes", downloadedBytes);
        data.put("totalBytes", totalBytes);
        notifyListeners("otaDownloadProgress", data);
    }

    private static String bytesToHex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            sb.append(String.format(Locale.ROOT, "%02x", b & 0xff));
        }
        return sb.toString();
    }
}
