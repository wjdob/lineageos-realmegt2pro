/* Read-only public battery-property snapshot; no charging or permission changes. */
import android.content.Context;
import android.os.BatteryManager;
import android.os.Looper;
import org.json.JSONObject;

public final class LineageBatteryProbe {
    private static Object value(BatteryManager manager, int property) {
        int result = manager.getIntProperty(property);
        return result == Integer.MIN_VALUE ? JSONObject.NULL : result;
    }
    public static void main(String[] args) throws Exception {
        Looper.prepare();
        Class<?> type = Class.forName("android.app.ActivityThread");
        Object thread = type.getMethod("systemMain").invoke(null);
        Context context = (Context) type.getMethod("getSystemContext").invoke(thread);
        BatteryManager manager = context.getSystemService(BatteryManager.class);
        if (manager == null) throw new IllegalStateException("Battery service unavailable");
        JSONObject report = new JSONObject()
                .put("capacity_percent", value(manager, BatteryManager.BATTERY_PROPERTY_CAPACITY))
                .put("charge_counter_microah", value(manager, BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER))
                .put("current_now_microamps", value(manager, BatteryManager.BATTERY_PROPERTY_CURRENT_NOW))
                .put("current_average_microamps", value(manager, BatteryManager.BATTERY_PROPERTY_CURRENT_AVERAGE))
                .put("status", value(manager, BatteryManager.BATTERY_PROPERTY_STATUS))
                .put("is_charging", manager.isCharging())
                .put("limits", "Framework-reported properties in an engineering process. Units are the API contract, not independent calibration or measured input power. Unsupported int properties are null; no settings, permissions, media, charging controls or partition writes.");
        System.out.println(report.toString()); System.out.flush(); System.exit(0);
    }
}
