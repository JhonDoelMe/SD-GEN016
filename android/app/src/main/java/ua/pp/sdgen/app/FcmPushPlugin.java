package ua.pp.sdgen.app;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Build;

import androidx.core.content.ContextCompat;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;
import com.google.firebase.FirebaseApp;
import com.google.firebase.messaging.FirebaseMessaging;

@CapacitorPlugin(
    name = "FcmPush",
    permissions = {
        @Permission(
            strings = { Manifest.permission.POST_NOTIFICATIONS },
            alias = "notifications"
        )
    }
)
public class FcmPushPlugin extends Plugin {

    private static volatile FcmPushPlugin activeInstance = null;

    @Override
    public void load() {
        super.load();
        activeInstance = this;
        SdgenFirebaseMessagingService.ensureChannels(getContext());
    }

    @Override
    protected void handleOnDestroy() {
        if (activeInstance == this) {
            activeInstance = null;
        }
        super.handleOnDestroy();
    }

    @PluginMethod
    public void getStatus(PluginCall call) {
        SdgenFirebaseMessagingService.ensureChannels(getContext());
        JSObject ret = new JSObject();
        ret.put("isFirebaseConfigured", isFirebaseInitialized());
        ret.put("permissionState", resolvePermissionState());
        call.resolve(ret);
    }

    @PluginMethod
    public void register(PluginCall call) {
        SdgenFirebaseMessagingService.ensureChannels(getContext());
        if (!hasNotificationPermission()) {
            requestPermissionForAlias("notifications", call, "notificationsPermCallback");
            return;
        }
        fetchTokenAndResolve(call);
    }

    @PermissionCallback
    private void notificationsPermCallback(PluginCall call) {
        if (call == null) {
            return;
        }
        if (!hasNotificationPermission()) {
            JSObject ret = new JSObject();
            ret.put("granted", false);
            ret.put("permissionState", resolvePermissionState());
            call.resolve(ret);
            return;
        }
        fetchTokenAndResolve(call);
    }

    private void fetchTokenAndResolve(PluginCall call) {
        if (!isFirebaseInitialized()) {
            call.reject("Firebase ще не налаштований у збірці APK (відсутній google-services.json).");
            return;
        }
        FirebaseMessaging.getInstance().getToken()
            .addOnCompleteListener(task -> {
                if (!task.isSuccessful() || task.getResult() == null) {
                    Exception ex = task.getException();
                    call.reject("Не вдалося отримати FCM токен: " + (ex != null ? ex.getMessage() : "невідома помилка"));
                    return;
                }
                JSObject ret = new JSObject();
                ret.put("granted", true);
                ret.put("permissionState", "granted");
                ret.put("token", task.getResult());
                call.resolve(ret);
            });
    }

    private boolean isFirebaseInitialized() {
        try {
            return !FirebaseApp.getApps(getContext()).isEmpty();
        } catch (Throwable ignored) {
            return false;
        }
    }

    private boolean hasNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            return true;
        }
        return ContextCompat.checkSelfPermission(
            getContext(),
            Manifest.permission.POST_NOTIFICATIONS
        ) == PackageManager.PERMISSION_GRANTED;
    }

    private String resolvePermissionState() {
        if (hasNotificationPermission()) {
            return "granted";
        }
        PermissionState state = getPermissionState("notifications");
        if (state == PermissionState.DENIED) {
            return "denied";
        }
        return "prompt";
    }

    public static void emitTokenRefresh(String token) {
        FcmPushPlugin instance = activeInstance;
        if (instance == null || token == null || token.isEmpty()) {
            return;
        }
        JSObject data = new JSObject();
        data.put("token", token);
        instance.notifyListeners("fcmTokenRefresh", data);
    }

    public static void emitPushReceived(String title, String body, String eventType, String logId) {
        FcmPushPlugin instance = activeInstance;
        if (instance == null) {
            return;
        }
        JSObject data = new JSObject();
        data.put("title", title != null ? title : "");
        data.put("body", body != null ? body : "");
        data.put("eventType", eventType != null ? eventType : "");
        data.put("logId", logId != null ? logId : "");
        instance.notifyListeners("fcmPushReceived", data);
    }
}
