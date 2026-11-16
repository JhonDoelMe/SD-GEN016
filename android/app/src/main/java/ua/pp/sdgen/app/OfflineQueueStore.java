package ua.pp.sdgen.app;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * Thread-safe SQLite backing store for the offline mutation queue in Android APK.
 * Mirrors the schema used by frontend/js/offline-queue.js so WebView and WorkManager
 * share a single source of truth.
 */
public final class OfflineQueueStore extends SQLiteOpenHelper {

    private static final String DB_NAME = "sdgen_offline_queue.db";
    private static final int DB_VERSION = 1;
    private static final String TABLE_QUEUE = "mutation_queue";

    private static volatile OfflineQueueStore instance;

    private OfflineQueueStore(Context ctx) {
        super(ctx.getApplicationContext(), DB_NAME, null, DB_VERSION);
    }

    public static OfflineQueueStore getInstance(Context ctx) {
        if (instance == null) {
            synchronized (OfflineQueueStore.class) {
                if (instance == null) {
                    instance = new OfflineQueueStore(ctx);
                }
            }
        }
        return instance;
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS " + TABLE_QUEUE + " ("
                + "id TEXT PRIMARY KEY, "
                + "idempotency_key TEXT NOT NULL, "
                + "action_type TEXT NOT NULL, "
                + "title TEXT NOT NULL, "
                + "summary TEXT NOT NULL, "
                + "endpoint TEXT NOT NULL, "
                + "method TEXT NOT NULL, "
                + "payload_json TEXT NOT NULL, "
                + "facility_id INTEGER, "
                + "facility_name TEXT, "
                + "generator_id INTEGER, "
                + "status TEXT NOT NULL, "
                + "error_message TEXT, "
                + "http_status INTEGER, "
                + "retry_count INTEGER NOT NULL DEFAULT 0, "
                + "created_at TEXT NOT NULL, "
                + "updated_at TEXT NOT NULL"
                + ")"
        );
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_oq_created_at ON " + TABLE_QUEUE + " (created_at ASC)");
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_oq_status ON " + TABLE_QUEUE + " (status)");
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        // Future migrations go here without dropping user mutations.
    }

    public synchronized List<JSONObject> getAll() {
        List<JSONObject> out = new ArrayList<>();
        SQLiteDatabase db = getReadableDatabase();
        try (Cursor c = db.query(TABLE_QUEUE, null, null, null, null, null, "created_at ASC")) {
            while (c.moveToNext()) {
                out.add(cursorToJson(c));
            }
        }
        return out;
    }

    public synchronized JSONArray getAllAsJsonArray() {
        JSONArray arr = new JSONArray();
        for (JSONObject obj : getAll()) {
            arr.put(obj);
        }
        return arr;
    }

    public synchronized List<JSONObject> getPending() {
        List<JSONObject> out = new ArrayList<>();
        SQLiteDatabase db = getReadableDatabase();
        try (Cursor c = db.query(
            TABLE_QUEUE,
            null,
            "status = ?",
            new String[] { "pending" },
            null,
            null,
            "created_at ASC"
        )) {
            while (c.moveToNext()) {
                out.add(cursorToJson(c));
            }
        }
        return out;
    }

    public synchronized int countPending() {
        SQLiteDatabase db = getReadableDatabase();
        try (Cursor c = db.rawQuery("SELECT COUNT(*) FROM " + TABLE_QUEUE + " WHERE status IN ('pending', 'syncing')", null)) {
            if (c.moveToFirst()) {
                return c.getInt(0);
            }
        }
        return 0;
    }

    public synchronized void put(JSONObject item) {
        if (item == null) return;
        String id = item.optString("id", "").trim();
        if (id.isEmpty()) return;

        ContentValues cv = new ContentValues();
        cv.put("id", id);
        cv.put("idempotency_key", item.optString("idempotency_key", id));
        cv.put("action_type", item.optString("action_type", "generic_mutation"));
        cv.put("title", item.optString("title", "Офлайн-операція"));
        cv.put("summary", item.optString("summary", ""));
        cv.put("endpoint", item.optString("endpoint", ""));
        cv.put("method", item.optString("method", "POST").toUpperCase());

        JSONObject payloadObj = item.optJSONObject("payload");
        cv.put("payload_json", payloadObj != null ? payloadObj.toString() : "{}");

        if (item.has("facility_id") && !item.isNull("facility_id")) {
            cv.put("facility_id", item.optLong("facility_id"));
        } else {
            cv.putNull("facility_id");
        }
        if (item.has("facility_name") && !item.isNull("facility_name")) {
            cv.put("facility_name", item.optString("facility_name"));
        } else {
            cv.putNull("facility_name");
        }
        if (item.has("generator_id") && !item.isNull("generator_id")) {
            cv.put("generator_id", item.optLong("generator_id"));
        } else {
            cv.putNull("generator_id");
        }

        cv.put("status", item.optString("status", "pending"));

        if (item.has("error_message") && !item.isNull("error_message")) {
            cv.put("error_message", item.optString("error_message"));
        } else {
            cv.putNull("error_message");
        }
        if (item.has("http_status") && !item.isNull("http_status")) {
            cv.put("http_status", item.optInt("http_status"));
        } else {
            cv.putNull("http_status");
        }

        cv.put("retry_count", item.optInt("retry_count", 0));
        cv.put("created_at", item.optString("created_at", ""));
        cv.put("updated_at", item.optString("updated_at", ""));

        SQLiteDatabase db = getWritableDatabase();
        db.insertWithOnConflict(TABLE_QUEUE, null, cv, SQLiteDatabase.CONFLICT_REPLACE);
    }

    public synchronized void delete(String id) {
        if (id == null || id.isEmpty()) return;
        SQLiteDatabase db = getWritableDatabase();
        db.delete(TABLE_QUEUE, "id = ?", new String[] { id });
    }

    public synchronized void clearAll() {
        SQLiteDatabase db = getWritableDatabase();
        db.delete(TABLE_QUEUE, null, null);
    }

    public synchronized int resetStuckSyncing(String nowIso) {
        SQLiteDatabase db = getWritableDatabase();
        ContentValues cv = new ContentValues();
        cv.put("status", "pending");
        if (nowIso != null && !nowIso.isEmpty()) {
            cv.put("updated_at", nowIso);
        }
        return db.update(TABLE_QUEUE, cv, "status = ?", new String[] { "syncing" });
    }

    private static JSONObject cursorToJson(Cursor c) {
        JSONObject obj = new JSONObject();
        try {
            obj.put("id", c.getString(c.getColumnIndexOrThrow("id")));
            obj.put("idempotency_key", c.getString(c.getColumnIndexOrThrow("idempotency_key")));
            obj.put("action_type", c.getString(c.getColumnIndexOrThrow("action_type")));
            obj.put("title", c.getString(c.getColumnIndexOrThrow("title")));
            obj.put("summary", c.getString(c.getColumnIndexOrThrow("summary")));
            obj.put("endpoint", c.getString(c.getColumnIndexOrThrow("endpoint")));
            obj.put("method", c.getString(c.getColumnIndexOrThrow("method")));

            String payloadStr = c.getString(c.getColumnIndexOrThrow("payload_json"));
            try {
                obj.put("payload", new JSONObject(payloadStr != null ? payloadStr : "{}"));
            } catch (Exception e) {
                obj.put("payload", new JSONObject());
            }

            int facIdx = c.getColumnIndexOrThrow("facility_id");
            obj.put("facility_id", c.isNull(facIdx) ? JSONObject.NULL : c.getLong(facIdx));

            int facNameIdx = c.getColumnIndexOrThrow("facility_name");
            obj.put("facility_name", c.isNull(facNameIdx) ? JSONObject.NULL : c.getString(facNameIdx));

            int genIdx = c.getColumnIndexOrThrow("generator_id");
            obj.put("generator_id", c.isNull(genIdx) ? JSONObject.NULL : c.getLong(genIdx));

            obj.put("status", c.getString(c.getColumnIndexOrThrow("status")));

            int errIdx = c.getColumnIndexOrThrow("error_message");
            obj.put("error_message", c.isNull(errIdx) ? JSONObject.NULL : c.getString(errIdx));

            int httpIdx = c.getColumnIndexOrThrow("http_status");
            obj.put("http_status", c.isNull(httpIdx) ? JSONObject.NULL : c.getInt(httpIdx));

            obj.put("retry_count", c.getInt(c.getColumnIndexOrThrow("retry_count")));
            obj.put("created_at", c.getString(c.getColumnIndexOrThrow("created_at")));
            obj.put("updated_at", c.getString(c.getColumnIndexOrThrow("updated_at")));
        } catch (Exception ignored) {}
        return obj;
    }
}
