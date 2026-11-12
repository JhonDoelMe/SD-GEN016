package ua.pp.sdgen.app;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;

import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

import java.util.Map;

public class SdgenFirebaseMessagingService extends FirebaseMessagingService {

    public static final String CHANNEL_ALERTS = "sdgen_alerts";
    public static final String CHANNEL_EVENTS = "sdgen_events";

    public static void ensureChannels(Context ctx) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = ctx.getSystemService(NotificationManager.class);
        if (manager == null) {
            return;
        }

        if (manager.getNotificationChannel(CHANNEL_ALERTS) == null) {
            NotificationChannel alerts = new NotificationChannel(
                CHANNEL_ALERTS,
                "Тривоги та аварії",
                NotificationManager.IMPORTANCE_HIGH
            );
            alerts.setDescription("Повітряні тривоги, критичні несправності, аварійні зупинки та низьке паливо");
            alerts.enableVibration(true);
            manager.createNotificationChannel(alerts);
        }

        if (manager.getNotificationChannel(CHANNEL_EVENTS) == null) {
            NotificationChannel events = new NotificationChannel(
                CHANNEL_EVENTS,
                "Робота генератора",
                NotificationManager.IMPORTANCE_DEFAULT
            );
            events.setDescription("Запуск та зупинка генератора, планове ТО та системні сповіщення");
            manager.createNotificationChannel(events);
        }
    }

    @Override
    public void onNewToken(@NonNull String token) {
        super.onNewToken(token);
        FcmPushPlugin.emitTokenRefresh(token);
    }

    @Override
    public void onMessageReceived(@NonNull RemoteMessage remoteMessage) {
        super.onMessageReceived(remoteMessage);
        ensureChannels(this);

        Map<String, String> data = remoteMessage.getData();
        RemoteMessage.Notification notif = remoteMessage.getNotification();

        String title = (notif != null && notif.getTitle() != null)
            ? notif.getTitle()
            : data.getOrDefault("title", "SD-GEN016");
        String body = (notif != null && notif.getBody() != null)
            ? notif.getBody()
            : data.getOrDefault("body", "");
        String eventType = data.getOrDefault("event_type", "");
        String logIdStr = data.getOrDefault("log_id", "");

        FcmPushPlugin.emitPushReceived(title, body, eventType, logIdStr);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
                return;
            }
        }

        boolean isHigh = "AIR_ALERT_START".equals(eventType)
            || "CRITICAL_FAULT".equals(eventType)
            || "GENERATOR_SAFETY_STOP".equals(eventType)
            || "GENERATOR_AUTO_STOP".equals(eventType)
            || "LOW_FUEL".equals(eventType)
            || "TEST".equals(eventType);

        Intent launchIntent = new Intent(this, MainActivity.class);
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if (eventType != null && !eventType.isEmpty()) {
            launchIntent.putExtra("event_type", eventType);
        }

        int pendingFlags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            pendingFlags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent pendingIntent = PendingIntent.getActivity(this, 0, launchIntent, pendingFlags);

        int notifId;
        try {
            notifId = !logIdStr.isEmpty() ? Integer.parseInt(logIdStr) : (int) (System.currentTimeMillis() & 0x7fffffff);
        } catch (NumberFormatException ignored) {
            notifId = (int) (System.currentTimeMillis() & 0x7fffffff);
        }

        NotificationCompat.Builder builder = new NotificationCompat.Builder(
            this,
            isHigh ? CHANNEL_ALERTS : CHANNEL_EVENTS
        )
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(isHigh ? NotificationCompat.PRIORITY_HIGH : NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent);

        NotificationManagerCompat.from(this).notify(notifId, builder.build());
    }
}
