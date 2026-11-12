package ua.pp.sdgen.app;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(OtaUpdaterPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
