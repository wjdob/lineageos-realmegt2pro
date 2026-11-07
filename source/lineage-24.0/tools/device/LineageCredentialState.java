/* Read-only public Keyguard status plus non-secret FRP state. Never reads credentials. */
import android.app.KeyguardManager;
import android.content.Context;
import android.os.Looper;
import org.json.JSONObject;

public final class LineageCredentialState {
    public static void main(String[] args) throws Exception {
        Looper.prepare();
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = activityThread.getMethod("systemMain").invoke(null);
        Context context = (Context)activityThread.getMethod("getSystemContext").invoke(thread);
        KeyguardManager keyguard = context.getSystemService(KeyguardManager.class);
        if (keyguard == null) throw new IllegalStateException("Keyguard service unavailable");
        JSONObject result = new JSONObject();
        result.put("device_secure", keyguard.isDeviceSecure());
        result.put("keyguard_secure", keyguard.isKeyguardSecure());
        result.put("device_locked", keyguard.isDeviceLocked());
        result.put("keyguard_locked", keyguard.isKeyguardLocked());
        Object persistent = context.getSystemService("persistent_data_block");
        result.put("frp_service_present", persistent != null);
        if (persistent != null) {
            Object active = persistent.getClass().getMethod("isFactoryResetProtectionActive")
                .invoke(persistent);
            result.put("frp_active", active);
        } else {
            result.put("frp_active", JSONObject.NULL);
        }
        result.put("limits", "Service-reported configuration/state only. Does not read PINs, "
            + "secrets, password handles or credential files; does not prove a physical unlock, "
            + "credential-encrypted storage access, biometric operation or recovery decryption.");
        System.out.println(result.toString());
        System.out.flush();
        System.exit(0);
    }
}
