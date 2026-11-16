package ua.pp.sdgen.app;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@CapacitorPlugin(name = "OfflineSync")
public class OfflineSyncPlugin extends Plugin {

    private static volatile OfflineSyncPlugin activeInstance = null;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

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

    public static void emitQueueUpdated(int synced, int conflicts, int deferred, boolean authRequired) {
        OfflineSyncPlugin inst = activeInstance;
        if (inst == null) return;
        try {
            JSObject payload = new JSObject();
            payload.put("synced", synced);
            payload.put("conflicts", conflicts);
            payload.put("deferred", deferred);
            payload.put("authRequired", authRequired);
            inst.notifyListeners("queueUpdated", payload);
        } catch (Exception ignored) {}
    }

    @PluginMethod
    public void setSessionContext(PluginCall call) {
        String apiBaseUrl = call.getString("apiBaseUrl", "");
        String authToken = call.getString("authToken", "");
        String userScope = call.getString("userScope", "");

        executor.execute(() -> {
            try {
                OfflineAuthVault.saveSessionContext(getContext(), apiBaseUrl, authToken, userScope);
                if (authToken != null && !authToken.trim().isEmpty()) {
                    OfflineSyncEngine.enqueueBackgroundSync(getContext(), false);
                }
                call.resolve(new JSObject().put("ok", true));
            } catch (Exception e) {
                call.reject("Не вдалося оновити офлайн-контекст сесії: " + e.getMessage(), e);
            }
        });
    }

    @PluginMethod
    public void clearAuthToken(PluginCall call) {
        executor.execute(() -> {
            OfflineAuthVault.clearAuthToken(getContext());
            call.resolve(new JSObject().put("ok", true));
        });
    }

    @PluginMethod
    public void queueGetAll(PluginCall call) {
        executor.execute(() -> {
            try {
                JSONArray items = OfflineQueueStore.getInstance(getContext()).getAllAsJsonArray();
                JSObject ret = new JSObject();
                ret.put("items", items);
                call.resolve(ret);
            } catch (Exception e) {
                call.reject("Помилка читання SQLite черги: " + e.getMessage(), e);
            }
        });
    }

    @PluginMethod
    public void queuePut(PluginCall call) {
        JSObject item = call.getObject("item");
        if (item == null) {
            call.reject("Відсутній об'єкт елемента черги.");
            return;
        }
        executor.execute(() -> {
            try {
                OfflineQueueStore store = OfflineQueueStore.getInstance(getContext());
                store.put(new JSONObject(item.toString()));
                if ("pending".equals(item.optString("status", "pending"))) {
                    OfflineSyncEngine.enqueueBackgroundSync(getContext(), false);
                }
                call.resolve(new JSObject().put("ok", true));
            } catch (Exception e) {
                call.reject("Помилка запису в SQLite чергу: " + e.getMessage(), e);
            }
        });
    }

    @PluginMethod
    public void queueDelete(PluginCall call) {
        String id = call.getString("id", "");
        executor.execute(() -> {
            try {
                OfflineQueueStore store = OfflineQueueStore.getInstance(getContext());
                store.delete(id);
                if (store.countPending() == 0) {
                    OfflineSyncEngine.cancelBackgroundSync(getContext());
                }
                call.resolve(new JSObject().put("ok", true));
            } catch (Exception e) {
                call.reject("Помилка видалення з SQLite черги: " + e.getMessage(), e);
            }
        });
    }

    @PluginMethod
    public void queueClear(PluginCall call) {
        executor.execute(() -> {
            try {
                OfflineQueueStore.getInstance(getContext()).clearAll();
                OfflineAuthVault.clearAll(getContext());
                OfflineSyncEngine.cancelBackgroundSync(getContext());
                call.resolve(new JSObject().put("ok", true));
            } catch (Exception e) {
                call.reject("Помилка очищення SQLite черги: " + e.getMessage(), e);
            }
        });
    }

    @PluginMethod
    public void recoverStuckSyncing(PluginCall call) {
        executor.execute(() -> {
            try {
                int recovered = OfflineQueueStore.getInstance(getContext())
                    .resetStuckSyncing(OfflineSyncEngine.nowUtcIso());
                call.resolve(new JSObject().put("recovered", recovered));
            } catch (Exception e) {
                call.reject("Помилка відновлення статусів черги: " + e.getMessage(), e);
            }
        });
    }

    @PluginMethod
    public void triggerBackgroundSync(PluginCall call) {
        boolean replace = Boolean.TRUE.equals(call.getBoolean("replace", false));
        executor.execute(() -> {
            try {
                OfflineSyncEngine.enqueueBackgroundSync(getContext(), replace);
                call.resolve(new JSObject().put("scheduled", true));
            } catch (Exception e) {
                call.reject("Не вдалося запланувати фонову синхронізацію: " + e.getMessage(), e);
            }
        });
    }

    @PluginMethod
    public void syncNow(PluginCall call) {
        executor.execute(() -> {
            try {
                OfflineSyncEngine.SyncResult res = OfflineSyncEngine.syncPending(getContext(), false);
                if (!res.authRequired && (res.offline || res.deferred > 0)) {
                    OfflineSyncEngine.enqueueBackgroundSync(getContext(), false);
                }
                JSObject ret = new JSObject();
                ret.put("synced", res.synced);
                ret.put("conflicts", res.conflicts);
                ret.put("deferred", res.deferred);
                ret.put("authRequired", res.authRequired);
                ret.put("offline", res.offline);
                call.resolve(ret);
            } catch (Exception e) {
                call.reject("Помилка нативної синхронізації: " + e.getMessage(), e);
            }
        });
    }
}
