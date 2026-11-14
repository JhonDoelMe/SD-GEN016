package ua.pp.sdgen.app;

import android.graphics.Color;
import android.os.Bundle;
import android.view.View;
import android.webkit.WebView;

import androidx.activity.OnBackPressedCallback;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsControllerCompat;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    private OnBackPressedCallback backCallback;

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

        backCallback = new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                WebView webView = (bridge != null) ? bridge.getWebView() : null;
                if (webView == null) {
                    performSystemBack();
                    return;
                }
                webView.evaluateJavascript(
                    "(function(){ return (typeof window.__handleNativeBack === 'function') ? Boolean(window.__handleNativeBack()) : false; })()",
                    value -> {
                        if ("true".equals(value)) {
                            return;
                        }
                        if (webView.canGoBack()) {
                            webView.goBack();
                        } else {
                            performSystemBack();
                        }
                    }
                );
            }
        };
        getOnBackPressedDispatcher().addCallback(this, backCallback);
    }

    @Override
    public void onResume() {
        super.onResume();
        if (backCallback != null) {
            backCallback.setEnabled(true);
        }
    }

    private void performSystemBack() {
        if (backCallback != null) {
            backCallback.setEnabled(false);
        }
        getOnBackPressedDispatcher().onBackPressed();
    }
}
