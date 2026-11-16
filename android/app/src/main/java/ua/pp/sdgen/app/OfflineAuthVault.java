package ua.pp.sdgen.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Encrypted credential & API context store for background WorkManager sync.
 * Encrypts the auth bearer token with an AndroidKeyStore AES-256-GCM key.
 */
public final class OfflineAuthVault {

    private static final String PREFS_NAME = "sdgen_offline_vault";
    private static final String KEY_ALIAS = "sdgen_offline_auth_key_v1";
    private static final String KEYSTORE_PROVIDER = "AndroidKeyStore";
    private static final String AES_GCM_TRANSFORMATION = "AES/GCM/NoPadding";
    private static final int GCM_TAG_BITS = 128;

    private static final String PREF_TOKEN_ENC = "auth_token_enc";
    private static final String PREF_API_BASE = "api_base_url";
    private static final String PREF_USER_SCOPE = "user_scope";
    private static final String PREF_AUTH_NOTIFIED = "auth_expiry_notified";

    private static final String DEFAULT_BASE_URL = "https://sdgen.pp.ua";

    private static volatile boolean appInForeground = false;

    private OfflineAuthVault() {}

    public static void setAppInForeground(boolean foreground) {
        appInForeground = foreground;
    }

    public static boolean isAppInForeground() {
        return appInForeground;
    }

    private static SharedPreferences prefs(Context ctx) {
        return ctx.getApplicationContext().getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    public static synchronized void saveSessionContext(Context ctx, String apiBaseUrl, String authToken, String userScope) {
        SharedPreferences.Editor editor = prefs(ctx).edit();
        if (apiBaseUrl != null && !apiBaseUrl.trim().isEmpty()) {
            editor.putString(PREF_API_BASE, apiBaseUrl.trim().replaceAll("/+$", ""));
        }
        if (userScope != null && !userScope.trim().isEmpty()) {
            editor.putString(PREF_USER_SCOPE, userScope.trim().toLowerCase());
        }
        if (authToken != null && !authToken.trim().isEmpty()) {
            String encrypted = encryptToken(authToken.trim());
            if (encrypted != null) {
                editor.putString(PREF_TOKEN_ENC, encrypted);
                editor.putBoolean(PREF_AUTH_NOTIFIED, false);
            }
        }
        editor.apply();
    }

    public static synchronized void clearAuthToken(Context ctx) {
        prefs(ctx).edit().remove(PREF_TOKEN_ENC).apply();
    }

    public static synchronized void clearAll(Context ctx) {
        prefs(ctx).edit()
            .remove(PREF_TOKEN_ENC)
            .remove(PREF_USER_SCOPE)
            .remove(PREF_AUTH_NOTIFIED)
            .apply();
    }

    public static synchronized String getAuthToken(Context ctx) {
        String raw = prefs(ctx).getString(PREF_TOKEN_ENC, "");
        if (raw == null || raw.isEmpty()) {
            return "";
        }
        String decrypted = decryptToken(raw);
        if (decrypted == null) {
            prefs(ctx).edit().remove(PREF_TOKEN_ENC).apply();
            return "";
        }
        return decrypted;
    }

    public static synchronized String getApiBaseUrl(Context ctx) {
        String url = prefs(ctx).getString(PREF_API_BASE, DEFAULT_BASE_URL);
        if (url == null || url.trim().isEmpty()) {
            return DEFAULT_BASE_URL;
        }
        return url.trim().replaceAll("/+$", "");
    }

    public static synchronized String getUserScope(Context ctx) {
        String s = prefs(ctx).getString(PREF_USER_SCOPE, "");
        return s != null ? s : "";
    }

    public static synchronized boolean wasAuthExpiryNotified(Context ctx) {
        return prefs(ctx).getBoolean(PREF_AUTH_NOTIFIED, false);
    }

    public static synchronized void setAuthExpiryNotified(Context ctx, boolean notified) {
        prefs(ctx).edit().putBoolean(PREF_AUTH_NOTIFIED, notified).apply();
    }

    private static SecretKey getOrCreateSecretKey() throws Exception {
        KeyStore ks = KeyStore.getInstance(KEYSTORE_PROVIDER);
        ks.load(null);
        if (ks.containsAlias(KEY_ALIAS)) {
            KeyStore.Entry entry = ks.getEntry(KEY_ALIAS, null);
            if (entry instanceof KeyStore.SecretKeyEntry) {
                return ((KeyStore.SecretKeyEntry) entry).getSecretKey();
            }
        }
        KeyGenerator keyGen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE_PROVIDER);
        keyGen.init(
            new KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        );
        return keyGen.generateKey();
    }

    private static String encryptToken(String plaintext) {
        try {
            SecretKey key = getOrCreateSecretKey();
            Cipher cipher = Cipher.getInstance(AES_GCM_TRANSFORMATION);
            cipher.init(Cipher.ENCRYPT_MODE, key);
            byte[] iv = cipher.getIV();
            byte[] cipherBytes = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
            return Base64.encodeToString(iv, Base64.NO_WRAP) + ":" + Base64.encodeToString(cipherBytes, Base64.NO_WRAP);
        } catch (Exception e) {
            return null;
        }
    }

    private static String decryptToken(String encoded) {
        try {
            int sep = encoded.indexOf(':');
            if (sep <= 0) return null;
            byte[] iv = Base64.decode(encoded.substring(0, sep), Base64.NO_WRAP);
            byte[] cipherBytes = Base64.decode(encoded.substring(sep + 1), Base64.NO_WRAP);

            KeyStore ks = KeyStore.getInstance(KEYSTORE_PROVIDER);
            ks.load(null);
            if (!ks.containsAlias(KEY_ALIAS)) return null;
            SecretKey key = ((KeyStore.SecretKeyEntry) ks.getEntry(KEY_ALIAS, null)).getSecretKey();

            Cipher cipher = Cipher.getInstance(AES_GCM_TRANSFORMATION);
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(GCM_TAG_BITS, iv));
            byte[] plain = cipher.doFinal(cipherBytes);
            return new String(plain, StandardCharsets.UTF_8);
        } catch (Exception e) {
            return null;
        }
    }
}
