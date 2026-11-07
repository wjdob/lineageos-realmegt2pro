/* Read-only engineering query of Android's loaded nominal power profile. */
import android.content.Context;
import android.os.Looper;
import org.json.JSONObject;

public final class LineagePowerProfileProbe {
    public static void main(String[] args) throws Exception {
        Looper.prepare();
        Class<?> activity = Class.forName("android.app.ActivityThread");
        Object thread = activity.getMethod("systemMain").invoke(null);
        Context context = (Context) activity.getMethod("getSystemContext").invoke(thread);
        Class<?> type = Class.forName("com.android.internal.os.PowerProfile");
        Object profile = type.getConstructor(Context.class).newInstance(context);
        double capacity = ((Number) type.getMethod("getBatteryCapacity").invoke(profile)).doubleValue();
        if (!Double.isFinite(capacity) || capacity <= 0) throw new IllegalStateException("Invalid nominal capacity");
        System.out.println(new JSONObject().put("loaded_nominal_capacity_mah", capacity)
                .put("limits", "Internal PowerProfile queried through reflection; configured nominal capacity, not a measured gauge capacity or battery-health diagnosis."));
        System.out.flush();
        System.exit(0);
    }
}
