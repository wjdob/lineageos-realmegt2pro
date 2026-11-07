/* Engineering framework sensor-delivery probe. No calibration or persistent settings. */
import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

public final class LineageSensorProbe implements SensorEventListener {
    private final Map<Integer, Stats> stats = new LinkedHashMap<>();
    private SensorManager manager;
    private long started;
    private long startedNanos;
    private static final int[] TYPES = {
        Sensor.TYPE_ACCELEROMETER, Sensor.TYPE_GYROSCOPE,
        Sensor.TYPE_MAGNETIC_FIELD, Sensor.TYPE_LIGHT, Sensor.TYPE_PROXIMITY
    };

    private static final class Stats {
        Sensor sensor;
        boolean registered;
        int samples;
        int freshSamples;
        int nonFinite;
        boolean monotonic = true;
        long first;
        long last;
        float[] values;
        float[] freshMinimum;
        float[] freshMaximum;
        int accuracy;
    }

    @Override public void onSensorChanged(SensorEvent event) {
        Stats s = stats.get(event.sensor.getType());
        if (s == null) return;
        if (s.samples != 0 && event.timestamp < s.last) s.monotonic = false;
        if (s.samples == 0) s.first = event.timestamp;
        s.last = event.timestamp;
        s.samples++;
        if (event.timestamp >= startedNanos) {
            s.freshSamples++;
            if (s.freshMinimum == null) {
                s.freshMinimum = new float[event.values.length];
                s.freshMaximum = new float[event.values.length];
                Arrays.fill(s.freshMinimum, Float.POSITIVE_INFINITY);
                Arrays.fill(s.freshMaximum, Float.NEGATIVE_INFINITY);
            }
            for (int i = 0; i < event.values.length; i++) if (Float.isFinite(event.values[i])) {
                s.freshMinimum[i] = Math.min(s.freshMinimum[i], event.values[i]);
                s.freshMaximum[i] = Math.max(s.freshMaximum[i], event.values[i]);
            }
        }
        s.values = event.values.clone();
        s.accuracy = event.accuracy;
        for (float v : s.values) if (!Float.isFinite(v)) s.nonFinite++;
    }

    @Override public void onAccuracyChanged(Sensor sensor, int accuracy) {}

    private void finish() {
        manager.unregisterListener(this);
        boolean delivered = true;
        JSONObject report = new JSONObject();
        JSONArray rows = new JSONArray();
        try {
            for (Map.Entry<Integer, Stats> entry : stats.entrySet()) {
                Stats s = entry.getValue();
                JSONObject row = new JSONObject();
                row.put("type", entry.getKey());
                row.put("present", s.sensor != null);
                row.put("registered", s.registered);
                row.put("samples", s.samples);
                row.put("fresh_samples", s.freshSamples);
                row.put("monotonic", s.monotonic);
                row.put("non_finite_values", s.nonFinite);
                row.put("accuracy_status", s.accuracy);
                row.put("first_timestamp_ns", s.first);
                row.put("last_timestamp_ns", s.last);
                if (s.sensor != null) {
                    row.put("name", s.sensor.getName());
                    row.put("vendor", s.sensor.getVendor());
                    row.put("wakeup", s.sensor.isWakeUpSensor());
                    row.put("maximum_range", s.sensor.getMaximumRange());
                }
                JSONArray values = new JSONArray();
                if (s.values != null) for (float v : s.values) {
                    values.put(Float.isFinite(v) ? (double) v : JSONObject.NULL);
                }
                row.put("last_values", values);
                JSONArray minimum = new JSONArray(), maximum = new JSONArray();
                if (s.freshMinimum != null) for (int i = 0; i < s.freshMinimum.length; i++) {
                    minimum.put(Float.isFinite(s.freshMinimum[i]) ? (double) s.freshMinimum[i] : JSONObject.NULL);
                    maximum.put(Float.isFinite(s.freshMaximum[i]) ? (double) s.freshMaximum[i] : JSONObject.NULL);
                }
                row.put("fresh_minimum_values", minimum);
                row.put("fresh_maximum_values", maximum);
                delivered &= s.registered && s.samples > 0 && s.monotonic && s.nonFinite == 0;
                rows.put(row);
            }
            report.put("duration_ms", SystemClock.elapsedRealtime() - started);
            report.put("started_elapsed_realtime_ns", startedNanos);
            report.put("sensors", rows);
            report.put("all_delivered_finite_events", delivered);
            report.put("limits", "Delivery and fresh per-axis range only; on-change sensors may return a cached initial state. Physical response requires a timed owner action; ranges alone do not prove calibration accuracy, suspend/resume or normal-use acceptance.");
            System.out.println(report.toString());
            System.out.flush();
            System.exit(delivered ? 0 : 3);
        } catch (Exception error) {
            error.printStackTrace();
            System.exit(4);
        }
    }

    public static void main(String[] args) throws Exception {
        int seconds = args.length == 0 ? 10 : Integer.parseInt(args[0]);
        if (seconds < 5 || seconds > 60) throw new IllegalArgumentException("5..60 seconds required");
        Looper.prepare();
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = activityThread.getMethod("systemMain").invoke(null);
        Context context = (Context) activityThread.getMethod("getSystemContext").invoke(thread);
        LineageSensorProbe probe = new LineageSensorProbe();
        probe.manager = context.getSystemService(SensorManager.class);
        Handler handler = new Handler(Looper.myLooper());
        probe.started = SystemClock.elapsedRealtime();
        probe.startedNanos = SystemClock.elapsedRealtimeNanos();
        for (int type : TYPES) {
            Stats s = new Stats();
            s.sensor = probe.manager.getDefaultSensor(type);
            probe.stats.put(type, s);
            if (s.sensor != null) s.registered = probe.manager.registerListener(probe, s.sensor, 100000, handler);
        }
        handler.postDelayed(probe::finish, seconds * 1000L);
        Looper.loop();
    }
}
