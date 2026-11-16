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

import androidx.activity.result.ActivityResult;
import androidx.annotation.RequiresApi;
import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
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

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private volatile String pendingCacheFilePath = null;
    private volatile String pendingSafeFileName = null;
    private volatile String pendingMimeType = null;
    private volatile boolean pendingOpenAfterSave = true;

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

                if (!cacheFile.exists() || cacheFile.length() <= 0) {
                    throw new IOException("Отримано порожній файл.");
                }

                String displayPath = "";
                String saveError = "";

                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    SaveOutcome outcome = saveToMediaStoreDownloads(ctx, cacheFile, safeFileName, mimeType);
                    displayPath = outcome.displayPath;
                    saveError = outcome.error;
                } else if (getPermissionState("storage") == PermissionState.GRANTED) {
                    SaveOutcome outcome = saveToLegacyDownloads(ctx, cacheFile, safeFileName, mimeType);
                    displayPath = outcome.displayPath;
                    saveError = outcome.error;
                } else {
                    saveError = "Немає дозволу на запис у Завантаження";
                }

                boolean savedToDownloads = !displayPath.isEmpty();

                // If automatic save to Downloads did not succeed, launch Android's Storage Access Framework
                // ("Save as...") picker so the user can save directly into any folder without permissions.
                if (!savedToDownloads) {
                    Activity activity = getActivity();
                    if (activity != null) {
                        pendingCacheFilePath = cacheFile.getAbsolutePath();
                        pendingSafeFileName = safeFileName;
                        pendingMimeType = mimeType;
                        pendingOpenAfterSave = openAfterSave;

                        Intent createDocIntent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                        createDocIntent.addCategory(Intent.CATEGORY_OPENABLE);
                        createDocIntent.setType(mimeType);
                        createDocIntent.putExtra(Intent.EXTRA_TITLE, safeFileName);

                        activity.runOnUiThread(() -> {
                            try {
                                startActivityForResult(call, createDocIntent, "handleCreateDocumentResult");
                            } catch (Exception ex) {
                                call.reject("Не вдалося зберегти файл у Завантаження: " + ex.getMessage(), ex);
                            }
                        });
                        return;
                    }
                }

                Uri shareUri = FileProvider.getUriForFile(
                    ctx,
                    ctx.getPackageName() + ".fileprovider",
                    cacheFile
                );

                final boolean finalSaved = savedToDownloads;
                final String finalPath = displayPath;
                final String finalError = saveError;

                if (openAfterSave) {
                    Activity activity = getActivity();
                    if (activity != null) {
                        activity.runOnUiThread(() -> {
                            OpenOutcome openOut = openOrShareUri(activity, shareUri, safeFileName, mimeType);
                            resolveResult(
                                call,
                                safeFileName,
                                finalSaved,
                                finalPath,
                                shareUri,
                                openOut.opened,
                                openOut.sharedViaChooser,
                                false,
                                finalError
                            );
                        });
                        return;
                    }
                }

                resolveResult(call, safeFileName, finalSaved, finalPath, shareUri, false, false, false, finalError);
            } catch (Exception e) {
                call.reject("Помилка збереження файлу: " + e.getMessage(), e);
            }
        });
    }

    @ActivityCallback
    private void handleCreateDocumentResult(PluginCall call, ActivityResult result) {
        if (call == null) {
            return;
        }
        final String cachePath = pendingCacheFilePath;
        final String safeFileName = pendingSafeFileName != null ? pendingSafeFileName : "sdgen_report.bin";
        final String mimeType = pendingMimeType != null ? pendingMimeType : "application/octet-stream";
        final boolean openAfterSave = pendingOpenAfterSave;
        pendingCacheFilePath = null;

        if (result == null || result.getResultCode() != Activity.RESULT_OK || result.getData() == null || result.getData().getData() == null) {
            resolveResult(call, safeFileName, false, "", null, false, false, true, "Збереження скасовано користувачем");
            return;
        }

        final Uri pickedUri = result.getData().getData();
        if (cachePath == null) {
            call.reject("Тимчасовий файл експорту втрачено.");
            return;
        }

        executor.execute(() -> {
            try {
                Context ctx = getContext();
                File srcFile = new File(cachePath);
                if (!srcFile.exists()) {
                    throw new IOException("Тимчасовий файл експорту не знайдено.");
                }

                try (
                    InputStream in = new BufferedInputStream(new FileInputStream(srcFile));
                    OutputStream out = ctx.getContentResolver().openOutputStream(pickedUri)
                ) {
                    if (out == null) {
                        throw new IOException("Не вдалося відкрити обраний файл для запису.");
                    }
                    byte[] buf = new byte[16384];
                    int read;
                    while ((read = in.read(buf)) != -1) {
                        out.write(buf, 0, read);
                    }
                    out.flush();
                }

                Uri shareUri = FileProvider.getUriForFile(
                    ctx,
                    ctx.getPackageName() + ".fileprovider",
                    srcFile
                );

                if (openAfterSave) {
                    Activity activity = getActivity();
                    if (activity != null) {
                        activity.runOnUiThread(() -> {
                            OpenOutcome openOut = openOrShareUri(activity, shareUri, safeFileName, mimeType);
                            resolveResult(
                                call,
                                safeFileName,
                                true,
                                "обраної папки/" + safeFileName,
                                pickedUri,
                                openOut.opened,
                                openOut.sharedViaChooser,
                                false,
                                ""
                            );
                        });
                        return;
                    }
                }

                resolveResult(call, safeFileName, true, "обраної папки/" + safeFileName, pickedUri, false, false, false, "");
            } catch (Exception e) {
                call.reject("Не вдалося записати файл у вибрану папку: " + e.getMessage(), e);
            }
        });
    }

    private OpenOutcome openOrShareUri(Activity activity, Uri uri, String fileName, String mimeType) {
        try {
            Intent viewIntent = new Intent(Intent.ACTION_VIEW);
            viewIntent.setDataAndType(uri, mimeType);
            viewIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            activity.startActivity(viewIntent);
            return new OpenOutcome(true, false);
        } catch (ActivityNotFoundException ignored) {
            try {
                Intent sendIntent = new Intent(Intent.ACTION_SEND);
                sendIntent.setType(mimeType);
                sendIntent.putExtra(Intent.EXTRA_STREAM, uri);
                sendIntent.putExtra(Intent.EXTRA_SUBJECT, fileName);
                sendIntent.setClipData(ClipData.newRawUri(fileName, uri));
                sendIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);

                Intent chooser = Intent.createChooser(sendIntent, "Відкрити або поділитися файлом");
                chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                activity.startActivity(chooser);
                return new OpenOutcome(false, true);
            } catch (Exception ignoredShare) {
                return new OpenOutcome(false, false);
            }
        }
    }

    private void resolveResult(
        PluginCall call,
        String fileName,
        boolean savedToDownloads,
        String displayPath,
        Uri uri,
        boolean opened,
        boolean sharedViaChooser,
        boolean canceled,
        String saveError
    ) {
        JSObject ret = new JSObject();
        ret.put("fileName", fileName);
        ret.put("savedToDownloads", savedToDownloads);
        ret.put("displayPath", displayPath);
        ret.put("cacheUri", uri != null ? uri.toString() : "");
        ret.put("opened", opened);
        ret.put("sharedViaChooser", sharedViaChooser);
        ret.put("canceled", canceled);
        if (saveError != null && !saveError.isEmpty()) {
            ret.put("saveError", saveError);
        }
        call.resolve(ret);
    }

    private void writeBase64ToFile(String base64Input, File destFile) throws IOException {
        String payload = base64Input;
        int commaIdx = base64Input.indexOf(',');
        if (commaIdx >= 0 && base64Input.substring(0, Math.min(commaIdx, 256)).contains("base64")) {
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
    private SaveOutcome saveToMediaStoreDownloads(Context ctx, File srcFile, String fileName, String mimeType) {
        SaveOutcome firstAttempt = insertIntoMediaStoreDownloads(ctx, srcFile, fileName, mimeType);
        if (!firstAttempt.displayPath.isEmpty()) {
            return firstAttempt;
        }
        if (!"application/octet-stream".equals(mimeType)) {
            SaveOutcome fallbackAttempt = insertIntoMediaStoreDownloads(ctx, srcFile, fileName, "application/octet-stream");
            if (!fallbackAttempt.displayPath.isEmpty()) {
                return fallbackAttempt;
            }
            return fallbackAttempt;
        }
        return firstAttempt;
    }

    @RequiresApi(api = Build.VERSION_CODES.Q)
    private SaveOutcome insertIntoMediaStoreDownloads(Context ctx, File srcFile, String fileName, String mimeType) {
        ContentResolver resolver = ctx.getContentResolver();
        ContentValues values = new ContentValues();
        values.put(MediaStore.MediaColumns.DISPLAY_NAME, fileName);
        values.put(MediaStore.MediaColumns.MIME_TYPE, mimeType);
        values.put(MediaStore.MediaColumns.SIZE, srcFile.length());
        values.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
        values.put(MediaStore.MediaColumns.IS_PENDING, 1);

        Uri itemUri = null;
        try {
            itemUri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
            if (itemUri == null) {
                return new SaveOutcome("", "MediaStore.Downloads повернув null");
            }

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
            return new SaveOutcome("Download/" + fileName, "");
        } catch (Exception e) {
            if (itemUri != null) {
                try {
                    resolver.delete(itemUri, null, null);
                } catch (Exception ignored) {}
            }
            return new SaveOutcome("", e.getMessage() != null ? e.getMessage() : "MediaStore error");
        }
    }

    @SuppressWarnings("deprecation")
    private SaveOutcome saveToLegacyDownloads(Context ctx, File srcFile, String fileName, String mimeType) {
        try {
            File targetDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
            if (!targetDir.exists() && !targetDir.mkdirs()) {
                return new SaveOutcome("", "Не вдалося створити папку Download");
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
            return new SaveOutcome("Download/" + targetFile.getName(), "");
        } catch (Exception e) {
            return new SaveOutcome("", e.getMessage() != null ? e.getMessage() : "Legacy write error");
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

    private static final class SaveOutcome {
        final String displayPath;
        final String error;

        SaveOutcome(String displayPath, String error) {
            this.displayPath = displayPath;
            this.error = error;
        }
    }

    private static final class OpenOutcome {
        final boolean opened;
        final boolean sharedViaChooser;

        OpenOutcome(boolean opened, boolean sharedViaChooser) {
            this.opened = opened;
            this.sharedViaChooser = sharedViaChooser;
        }
    }
}
