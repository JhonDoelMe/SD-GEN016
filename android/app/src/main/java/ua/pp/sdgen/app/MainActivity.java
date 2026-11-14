package ua.pp.sdgen.app;

import android.graphics.Color;
import android.os.Bundle;
import android.view.View;

import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsControllerCompat;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(OtaUpdaterPlugin.class);
        registerPlugin(FcmPushPlugin.class);
        super.onCreate(savedInstanceState);

        // Capacitor 8 SystemBars handles WindowInsets (system bars + IME) on decorView;
        // do not re-apply IME padding on android.R.id.content or the keyboard gap doubles.
        View decorView = getWindow().getDecorView();
        decorView.setBackgroundColor(Color.parseColor("#0f172a"));
        WindowInsetsControllerCompat controller = WindowCompat.getInsetsController(getWindow(), decorView);
        if (controller != null) {
            controller.setAppearanceLightStatusBars(false);
            controller.setAppearanceLightNavigationBars(false);
        }
    }
}
