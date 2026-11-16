package ua.pp.sdgen.app;

import android.Manifest;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.Build;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;
import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;
import java.util.concurrent.TimeUnit;

/**
 * Single locked synchronization engine shared by foreground JS calls (OfflineSyncPlugin)
 * and background OS tasks (OfflineSyncWorker). Ensures at most one thread transmits
 * queued mutations at a time and handles 2xx, 401, 4xx conflicts and transient 5xx/network errors.
 */
public final class OfflineSyncEngine {

    public static final String UNIQUE_WORK_NAME = "sdgen_offline_sync_work";

    private static final int CONNECT_TIMEOUT_MS = 15000;
    private static final int READ_TIMEOUT_MS = 15000;
    private static final int NOTIF_ID_BG_SYNC = 4201;
    private static final int NOTIF_ID_BG_AUTH = 4202;

    private static final Object SYNC_LOCK = new Object();

    private OfflineSyncEngine() {}

    public static final class SyncResult {
        public final int synced;
        public final int conflicts;
        public final int deferred;
        public final boolean authRequired;
        public final boolean offline;

        SyncResult(int synced, int conflicts, int deferred, boolean authRequired, boolean offline) {
            this.synced = synced;
            this.conflicts = conflicts;
            this.deferred = deferred;
            this.authRequired = authRequired;
            this.offline = offline;
        }
    }

    public static String nowUtcIso() {
        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
        sdf.setTimeZone(TimeZone.getTimeZone("UTC"));
        return sdf.format(new Date());
    }

    public static void enqueueBackgroundSync(Context ctx, boolean replaceExisting) {
        Context appCtx = ctx.getApplicationContext();
        OfflineQueueStore store = OfflineQueueStore.getInstance(appCtx);
        if (store.countPending() <= 0) {
            return;
        }

        Constraints constraints = new Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build();

        OneTimeWorkRequest req = new OneTimeWorkRequest.Builder(OfflineSyncWorker.class)
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
            .build();

        WorkManager.getInstance(appCtx).enqueueUniqueWork(
            UNIQUE_WORK_NAME,
            replaceExisting ? ExistingWorkPolicy.REPLACE : ExistingWorkPolicy.KEEP,
            req
        );
    }

    public static void cancelBackgroundSync(Context ctx) {
        WorkManager.getInstance(ctx.getApplicationContext()).cancelUniqueWork(UNIQUE_WORK_NAME);
    }

    public static boolean isNetworkConnected(Context ctx) {
        ConnectivityManager cm = (ConnectivityManager) ctx.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) return false;
        Network active = cm.getActiveNetwork();
        if (active == null) return false;
        NetworkCapabilities caps = cm.getNetworkCapabilities(active);
        return caps != null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
    }

    public static SyncResult syncPending(Context ctx, boolean fromBackgroundWorker) {
        Context appCtx = ctx.getApplicationContext();
        synchronized (SYNC_LOCK) {
            OfflineQueueStore store = OfflineQueueStore.getInstance(appCtx);
            store.resetStuckSyncing(nowUtcIso());

            List<JSONObject> pending = store.getPending();
            if (pending.isEmpty()) {
                return new SyncResult(0, 0, 0, false, false);
            }

            if (!isNetworkConnected(appCtx)) {
                return new SyncResult(0, 0, pending.size(), false, true);
            }

            String authToken = OfflineAuthVault.getAuthToken(appCtx);
            if (authToken.isEmpty()) {
                if (fromBackgroundWorker && !OfflineAuthVault.wasAuthExpiryNotified(appCtx)) {
                    OfflineAuthVault.setAuthExpiryNotified(appCtx, true);
                    showStatusNotification(
                        appCtx,
                        NOTIF_ID_BG_AUTH,
                        SdgenFirebaseMessagingService.CHANNEL_ALERTS,
                        "SD-GEN016: Потрібен вхід",
                        "Є відкладені події (" + pending.size() + "). Відкрийте додаток та увійдіть для відправки."
                    );
                }
                return new SyncResult(0, 0, pending.size(), true, false);
            }

            String baseUrl = OfflineAuthVault.getApiBaseUrl(appCtx);
            if (!isAllowedHttpsBaseUrl(baseUrl)) {
                return new SyncResult(0, 0, pending.size(), false, true);
            }

            int syncedCount = 0;
            int conflictCount = 0;
            int deferredCount = 0;
            boolean authRequired = false;
            boolean networkError = false;

            for (JSONObject item : pending) {
                String id = item.optString("id", "");
                try {
                    item.put("status", "syncing");
                    store.put(item);

                    TransmitOutcome outcome = sendSingleItem(baseUrl, authToken, item);
                    if (outcome.kind == TransmitKind.NETWORK_ERROR) {
                        item.put("status", "pending");
                        item.put("updated_at", nowUtcIso());
                        store.put(item);
                        deferredCount += 1;
                        networkError = true;
                        break;
                    }
                    if (outcome.kind == TransmitKind.AUTH_REQUIRED) {
                        item.put("status", "pending");
                        item.put("updated_at", nowUtcIso());
                        store.put(item);
                        OfflineAuthVault.clearAuthToken(appCtx);
                        authRequired = true;
                        deferredCount += 1;
                        if (fromBackgroundWorker && !OfflineAuthVault.wasAuthExpiryNotified(appCtx)) {
                            OfflineAuthVault.setAuthExpiryNotified(appCtx, true);
                            showStatusNotification(
                                appCtx,
                                NOTIF_ID_BG_AUTH,
                                SdgenFirebaseMessagingService.CHANNEL_ALERTS,
                                "SD-GEN016: Сесія закінчилась",
                                "Увійдіть у додаток для синхронізації відкладених дій."
                            );
                        }
                        break;
                    }
                    if (outcome.kind == TransmitKind.SYNCED) {
                        store.delete(id);
                        syncedCount += 1;
                    } else {
                        item.put("status", "conflict");
                        item.put("http_status", outcome.httpStatus);
                        item.put("error_message", outcome.message);
                        item.put("retry_count", item.optInt("retry_count", 0) + 1);
                        item.put("updated_at", nowUtcIso());
                        store.put(item);
                        conflictCount += 1;
                    }
                } catch (Exception e) {
                    try {
                        item.put("status", "pending");
                        item.put("updated_at", nowUtcIso());
                        store.put(item);
                    } catch (Exception ignored) {}
                    deferredCount += 1;
                    networkError = true;
                    break;
                }
            }

            if (fromBackgroundWorker && !OfflineAuthVault.isAppInForeground()) {
                if (syncedCount > 0 && conflictCount == 0) {
                    showStatusNotification(
                        appCtx,
                        NOTIF_ID_BG_SYNC,
                        SdgenFirebaseMessagingService.CHANNEL_EVENTS,
                        "SD-GEN016: Фонова синхронізація",
                        "Відкладені операції успішно доставлено на сервер (" + syncedCount + ")."
                    );
                } else if (conflictCount > 0) {
                    showStatusNotification(
                        appCtx,
                        NOTIF_ID_BG_SYNC,
                        SdgenFirebaseMessagingService.CHANNEL_ALERTS,
                        "SD-GEN016: Конфлікт синхронізації",
                        "Синхронізовано: " + syncedCount + ", потребують перевірки вручну: " + conflictCount + "."
                    );
                }
            }

            OfflineSyncPlugin.emitQueueUpdated(syncedCount, conflictCount, deferredCount, authRequired);
            return new SyncResult(syncedCount, conflictCount, deferredCount, authRequired, networkError);
        }
    }

    private enum TransmitKind {
        SYNCED,
        NETWORK_ERROR,
        AUTH_REQUIRED,
        CONFLICT
    }

    private static final class TransmitOutcome {
        final TransmitKind kind;
        final int httpStatus;
        final String message;

        TransmitOutcome(TransmitKind kind, int httpStatus, String message) {
            this.kind = kind;
            this.httpStatus = httpStatus;
            this.message = message;
        }
    }

    private static TransmitOutcome sendSingleItem(String baseUrl, String authToken, JSONObject item) {
        String endpoint = item.optString("endpoint", "");
        String method = item.optString("method", "POST").toUpperCase(Locale.ROOT);
        String idemKey = item.optString("idempotency_key", "");
        JSONObject payload = item.optJSONObject("payload");
        if (payload == null) {
            payload = new JSONObject();
        }
        try {
            payload.put("idempotency_key", idemKey);
        } catch (Exception ignored) {}

        HttpURLConnection conn = null;
        try {
            URL url = new URL(baseUrl + "/api/v1" + endpoint);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod(method);
            conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
            conn.setReadTimeout(READ_TIMEOUT_MS);
            conn.setInstanceFollowRedirects(false);
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            conn.setRequestProperty("Authorization", "Bearer " + authToken);
            if (!idemKey.isEmpty()) {
                conn.setRequestProperty("Idempotency-Key", idemKey);
            }

            byte[] bodyBytes = payload.toString().getBytes(StandardCharsets.UTF_8);
            conn.setFixedLengthStreamingMode(bodyBytes.length);
            try (OutputStream os = conn.getOutputStream()) {
                os.write(bodyBytes);
                os.flush();
            }

            int status = conn.getResponseCode();
            if (status == 408 || status == 502 || status == 503 || status == 504) {
                return new TransmitOutcome(TransmitKind.NETWORK_ERROR, status, "Сервер тимчасово недоступний");
            }
            if (status == 401) {
                return new TransmitOutcome(TransmitKind.AUTH_REQUIRED, status, "Сесія закінчилась");
            }
            if (status >= 200 && status < 300) {
                return new TransmitOutcome(TransmitKind.SYNCED, status, "");
            }

            InputStream errStream = conn.getErrorStream();
            String rawErr = readStreamQuietly(errStream != null ? errStream : conn.getInputStream());
            String parsedMsg = extractServerError(rawErr, "Помилка сервера (" + status + ")");
            return new TransmitOutcome(TransmitKind.CONFLICT, status, parsedMsg);
        } catch (Exception e) {
            return new TransmitOutcome(TransmitKind.NETWORK_ERROR, 0, e.getMessage() != null ? e.getMessage() : "Помилка мережі");
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private static boolean isAllowedHttpsBaseUrl(String baseUrl) {
        if (baseUrl == null || !baseUrl.startsWith("https://")) {
            return false;
        }
        try {
            URL parsed = new URL(baseUrl);
            String host = parsed.getHost() != null ? parsed.getHost().trim().toLowerCase(Locale.ROOT) : "";
            return !host.isEmpty() && !"localhost".equals(host) && !host.startsWith("127.") && !"169.254.169.254".equals(host);
        } catch (Exception e) {
            return false;
        }
    }

    private static String readStreamQuietly(InputStream is) {
        if (is == null) return "";
        try (BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = br.readLine()) != null) {
                sb.append(line);
                if (sb.length() > 4096) break;
            }
            return sb.toString();
        } catch (Exception e) {
            return "";
        }
    }

    private static String extractServerError(String rawBody, String fallback) {
        if (rawBody == null || rawBody.trim().isEmpty()) {
            return fallback;
        }
        try {
            JSONObject obj = new JSONObject(rawBody);
            if (!obj.has("detail")) {
                return fallback;
            }
            Object detail = obj.get("detail");
            if (detail instanceof String) {
                return ((String) detail).trim();
            }
            if (detail instanceof JSONArray) {
                JSONArray arr = (JSONArray) detail;
                StringBuilder sb = new StringBuilder();
                for (int i = 0; i < arr.length(); i++) {
                    JSONObject item = arr.optJSONObject(i);
                    String msg = item != null ? item.optString("msg", "") : arr.optString(i, "");
                    msg = msg.replaceFirst("(?i)^Value error,\\s*", "").trim();
                    if (!msg.isEmpty()) {
                        if (sb.length() > 0) sb.append("; ");
                        sb.append(msg);
                    }
                }
                if (sb.length() > 0) return sb.toString();
            }
        } catch (Exception ignored) {}
        return fallback;
    }

    private static void showStatusNotification(
        Context ctx,
        int notifId,
        String channelId,
        String title,
        String body
    ) {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                    return;
                }
            }
            SdgenFirebaseMessagingService.ensureChannels(ctx);

            Intent launchIntent = new Intent(ctx, MainActivity.class);
            launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            int flags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                flags |= PendingIntent.FLAG_IMMUTABLE;
            }
            PendingIntent pendingIntent = PendingIntent.getActivity(ctx, notifId, launchIntent, flags);

            int priority = SdgenFirebaseMessagingService.CHANNEL_ALERTS.equals(channelId)
                ? NotificationCompat.PRIORITY_HIGH
                : NotificationCompat.PRIORITY_DEFAULT;

            NotificationCompat.Builder builder = new NotificationCompat.Builder(ctx, channelId)
                .setSmallIcon(R.drawable.ic_stat_sdgen)
                .setColor(ContextCompat.getColor(ctx, R.color.sdgen_notification_color))
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
                .setAutoCancel(true)
                .setPriority(priority)
                .setContentIntent(pendingIntent);

            NotificationManagerCompat.from(ctx).notify(notifId, builder.build());
        } catch (Exception ignored) {}
    }
}
