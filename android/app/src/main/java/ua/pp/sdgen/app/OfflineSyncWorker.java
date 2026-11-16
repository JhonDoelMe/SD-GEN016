package ua.pp.sdgen.app;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

/**
 * Android WorkManager worker that drains pending offline mutations even when the app
 * is swiped away or the screen is off, once network connectivity is available.
 */
public class OfflineSyncWorker extends Worker {

    public OfflineSyncWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    @NonNull
    @Override
    public Result doWork() {
        OfflineSyncEngine.SyncResult result = OfflineSyncEngine.syncPending(getApplicationContext(), true);
        if (result.authRequired) {
            // Wait until the user signs in again; JS will re-enqueue WorkManager after login.
            return Result.success();
        }
        if (result.offline || result.deferred > 0) {
            return Result.retry();
        }
        return Result.success();
    }
}
