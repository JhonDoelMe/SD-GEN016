package ua.pp.sdgen.app;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;
import android.webkit.MimeTypeMap;

import androidx.annotation.RequiresApi;
import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.io.BufferedInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@CapacitorPlugin(
    name = "FileDownload",
    permissions = {
        @Permission(
            strings = { Manifest.permission.WRITE_EXTERNAL_STORAGE },
            alias = "storage"
        )
    }
)
public class FileDownloadPlugin extends Plugin {

    private static final int CONNECT_TIMEOUT_MS = 15000;
    private static final int READ_TIMEOUT_MS = 60000;
    private static final long MAX_CACHE_AGE_MS = 24L * 60L * 60L * 1000L;
    private static final String DOWNLOAD_SUBDIR = "SD-GEN016";

    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    @PluginMethod
    public void saveAndOpen(PluginCall call) {
        String base64Data = call.getString("base64Data");
        String downloadUrl = call.getString("url");

        if ((base64Data == null || base64Data.isEmpty()) && (downloadUrl == null || downloadUrl.isEmpty())) {
            call.reject("Не передано дані файлу для збереження.");
            return;
        }

        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q
            && getPermissionState("storage") != PermissionState.GRANTED) {
            requestPermissionForAlias("storage", call, "storagePermsCallback");
            return;
        }

        executeSaveAndOpen(call);
    }

    @PermissionCallback
    private void storagePermsCallback(PluginCall call) {
        // Proceed even if legacy external storage permission was denied:
        // the file is still written to private cacheDir and shared/opened via FileProvider.
        executeSaveAndOpen(call);
    }

    private void executeSaveAndOpen(PluginCall call) {
        final String rawFileName = call.getString("fileName", "sdgen_report.bin");
        final String safeFileName = sanitizeFileName(rawFileName);
        final String mimeType = resolveMimeType(call.getString("mimeType"), safeFileName);
        final String base64Data = call.getString("base64Data");
        final String downloadUrl = call.getString("url");
        final String authHeader = call.getString("authHeader");
        final boolean openAfterSave = call.getBoolean("openAfterSave", true);

        executor.execute(() -> {
            try {
                Context ctx = getContext();
                File cacheDir = new File(ctx.getCacheDir(), "exports");
                if (!cacheDir.exists() && !cacheDir.mkdirs()) {
                    throw new IOException("Не вдалося створити тимчасову теку експорту.");
                }
                cleanupOldCacheFiles(cacheDir);

                File cacheFile = new File(cacheDir, safeFileName);
                if (base64Data != null && !base64Data.isEmpty()) {
                    writeBase64ToFile(base64Data, cacheFile);
                } else {
                    streamHttpsToFile(downloadUrl, authHeader, cacheFile);
                }

                boolean savedToDownloads = false;
                String displayPath = "";

                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    displayPath = saveToMediaStoreDownloads(ctx, cacheFile, safeFileName, mimeType);
                    savedToDownloads = !displayPath.isEmpty();
                } else if (getPermissionState("storage") == PermissionState.GRANTED) {
                    displayPath = saveToLegacyDownloads(ctx, cacheFile, safeFileName, mimeType);
                    savedToDownloads = !displayPath.isEmpty();
                }

                Uri shareUri = FileProvider.getUriForFile(
                    ctx,
                    ctx.getPackageName() + ".fileprovider",
                    cacheFile
                );

                final boolean finalSaved = savedToDownloads;
                final String finalPath = displayPath;

                if (openAfterSave) {
                    Activity activity = getActivity();
                    if (activity != null) {
                        activity.runOnUiThread(() -> {
                            boolean opened = false;
                            boolean sharedViaChooser = false;
                            try {
                                Intent viewIntent = new Intent(Intent.ACTION_VIEW);
                                viewIntent.setDataAndType(shareUri, mimeType);
                                viewIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                                activity.startActivity(viewIntent);
                                opened = true;
                            } catch (ActivityNotFoundException ignored) {
                                try {
                                    Intent sendIntent = new Intent(Intent.ACTION_SEND);
                                    sendIntent.setType(mimeType);
                                    sendIntent.putExtra(Intent.EXTRA_STREAM, shareUri);
                                    sendIntent.putExtra(Intent.EXTRA_SUBJECT, safeFileName);
                                    sendIntent.setClipData(ClipData.newRawUri(safeFileName, shareUri));
                                    sendIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);

                                    Intent chooser = Intent.createChooser(sendIntent, "Відкрити або зберегти файл");
                                    chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                                    activity.startActivity(chooser);
                                    sharedViaChooser = true;
                                } catch (Exception ignoredShare) {
                                    // Saved to Downloads even if no viewer/share target is available
                                }
                            }
                            resolveResult(call, safeFileName, finalSaved, finalPath, shareUri, opened, sharedViaChooser);
                        });
                        return;
                    }
                }

                resolveResult(call, safeFileName, finalSaved, finalPath, shareUri, false, false);
            } catch (Exception e) {
                call.reject("Помилка збереження файлу: " + e.getMessage(), e);
            }
        });
    }

    private void resolveResult(
        PluginCall call,
        String fileName,
        boolean savedToDownloads,
        String displayPath,
        Uri shareUri,
        boolean opened,
        boolean sharedViaChooser
    ) {
        JSObject ret = new JSObject();
        ret.put("fileName", fileName);
        ret.put("savedToDownloads", savedToDownloads);
        ret.put("displayPath", displayPath);
        ret.put("cacheUri", shareUri != null ? shareUri.toString() : "");
        ret.put("opened", opened);
        ret.put("sharedViaChooser", sharedViaChooser);
        call.resolve(ret);
    }

    private void writeBase64ToFile(String base64Input, File destFile) throws IOException {
        String payload = base64Input;
        int commaIdx = base64Input.indexOf(',');
        if (commaIdx >= 0 && base64Input.substring(0, Math.min(commaIdx, 64)).contains("base64")) {
            payload = base64Input.substring(commaIdx + 1);
        }
        byte[] decoded = Base64.decode(payload, Base64.DEFAULT);
        try (FileOutputStream fos = new FileOutputStream(destFile)) {
            fos.write(decoded);
            fos.flush();
        }
    }

    private void streamHttpsToFile(String downloadUrl, String authHeader, File destFile) throws IOException {
        if (downloadUrl == null || !downloadUrl.startsWith("https://")) {
            throw new IOException("Некоректний HTTPS URL для завантаження.");
        }
        URL parsed = new URL(downloadUrl);
        String host = parsed.getHost() != null ? parsed.getHost().trim().toLowerCase(Locale.ROOT) : "";
        if (host.isEmpty() || "localhost".equals(host) || host.startsWith("127.") || "169.254.169.254".equals(host)) {
            throw new IOException("Неприпустимий хост для завантаження файлу.");
        }

        HttpURLConnection conn = (HttpURLConnection) parsed.openConnection();
        conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
        conn.setReadTimeout(READ_TIMEOUT_MS);
        conn.setInstanceFollowRedirects(false);
        if (authHeader != null && !authHeader.isEmpty()) {
            conn.setRequestProperty("Authorization", authHeader);
        }

        try {
            int code = conn.getResponseCode();
            if (code < 200 || code >= 300) {
                throw new IOException("Сервер повернув HTTP " + code);
            }
            try (
                InputStream in = new BufferedInputStream(conn.getInputStream());
                FileOutputStream out = new FileOutputStream(destFile)
            ) {
                byte[] buf = new byte[16384];
                int read;
                while ((read = in.read(buf)) != -1) {
                    out.write(buf, 0, read);
                }
                out.flush();
            }
        } finally {
            conn.disconnect();
        }
    }

    @RequiresApi(api = Build.VERSION_CODES.Q)
    private String saveToMediaStoreDownloads(Context ctx, File srcFile, String fileName, String mimeType) {
        ContentResolver resolver = ctx.getContentResolver();
        ContentValues values = new ContentValues();
        values.put(MediaStore.MediaColumns.DISPLAY_NAME, fileName);
        values.put(MediaStore.MediaColumns.MIME_TYPE, mimeType);
        values.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + File.separator + DOWNLOAD_SUBDIR);
        values.put(MediaStore.MediaColumns.IS_PENDING, 1);

        Uri itemUri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
        if (itemUri == null) {
            return "";
        }

        try {
            try (
                InputStream in = new BufferedInputStream(new FileInputStream(srcFile));
                OutputStream out = resolver.openOutputStream(itemUri)
            ) {
                if (out == null) {
                    throw new IOException("Не вдалося відкрити потік запису MediaStore.");
                }
                byte[] buf = new byte[16384];
                int read;
                while ((read = in.read(buf)) != -1) {
                    out.write(buf, 0, read);
                }
                out.flush();
            }

            ContentValues ready = new ContentValues();
            ready.put(MediaStore.MediaColumns.IS_PENDING, 0);
            resolver.update(itemUri, ready, null, null);
            return "Downloads/" + DOWNLOAD_SUBDIR + "/" + fileName;
        } catch (Exception e) {
            try {
                resolver.delete(itemUri, null, null);
            } catch (Exception ignored) {}
            return "";
        }
    }

    @SuppressWarnings("deprecation")
    private String saveToLegacyDownloads(Context ctx, File srcFile, String fileName, String mimeType) {
        try {
            File downloadsRoot = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
            File targetDir = new File(downloadsRoot, DOWNLOAD_SUBDIR);
            if (!targetDir.exists() && !targetDir.mkdirs()) {
                return "";
            }
            File targetFile = resolveUniqueLegacyFile(targetDir, fileName);
            try (
                InputStream in = new BufferedInputStream(new FileInputStream(srcFile));
                FileOutputStream out = new FileOutputStream(targetFile)
            ) {
                byte[] buf = new byte[16384];
                int read;
                while ((read = in.read(buf)) != -1) {
                    out.write(buf, 0, read);
                }
                out.flush();
            }
            MediaScannerConnection.scanFile(
                ctx,
                new String[] { targetFile.getAbsolutePath() },
                new String[] { mimeType },
                null
            );
            return "Downloads/" + DOWNLOAD_SUBDIR + "/" + targetFile.getName();
        } catch (Exception e) {
            return "";
        }
    }

    private File resolveUniqueLegacyFile(File dir, String fileName) {
        File candidate = new File(dir, fileName);
        if (!candidate.exists()) {
            return candidate;
        }
        int dot = fileName.lastIndexOf('.');
        String stem = dot > 0 ? fileName.substring(0, dot) : fileName;
        String ext = dot > 0 ? fileName.substring(dot) : "";
        for (int i = 1; i <= 99; i++) {
            File alt = new File(dir, stem + " (" + i + ")" + ext);
            if (!alt.exists()) {
                return alt;
            }
        }
        return new File(dir, stem + "_" + System.currentTimeMillis() + ext);
    }

    private void cleanupOldCacheFiles(File cacheDir) {
        File[] files = cacheDir.listFiles();
        if (files == null) return;
        long cutoff = System.currentTimeMillis() - MAX_CACHE_AGE_MS;
        for (File f : files) {
            if (f.isFile() && f.lastModified() < cutoff) {
                //noinspection ResultOfMethodCallIgnored
                f.delete();
            }
        }
    }

    private String sanitizeFileName(String raw) {
        String name = (raw == null) ? "" : raw.trim();
        name = name.replace('\\', '_').replace('/', '_');
        name = name.replaceAll("\\.\\.+", ".");
        name = name.replaceAll("[\\x00-\\x1F:*?\"<>|]", "_");
        while (name.startsWith(".")) {
            name = name.substring(1);
        }
        if (name.isEmpty()) {
            name = "sdgen_report.bin";
        }
        if (name.length() > 120) {
            int dot = name.lastIndexOf('.');
            String ext = (dot > 0 && name.length() - dot <= 10) ? name.substring(dot) : "";
            name = name.substring(0, 120 - ext.length()) + ext;
        }
        return name;
    }

    private String resolveMimeType(String providedMime, String fileName) {
        if (providedMime != null && !providedMime.trim().isEmpty()) {
            return providedMime.trim();
        }
        String lower = fileName.toLowerCase(Locale.ROOT);
        if (lower.endsWith(".xlsx")) {
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
        }
        if (lower.endsWith(".pdf")) {
            return "application/pdf";
        }
        if (lower.endsWith(".zip")) {
            return "application/zip";
        }
        int dot = lower.lastIndexOf('.');
        if (dot >= 0 && dot + 1 < lower.length()) {
            String ext = lower.substring(dot + 1);
            String guessed = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext);
            if (guessed != null && !guessed.isEmpty()) {
                return guessed;
            }
        }
        return "application/octet-stream";
    }
}
