/* Metadata-only engineering probe: never opens a CameraDevice or capture session. */
import android.content.Context;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.os.Looper;
import android.util.Size;
import java.util.ArrayList;
import java.util.Collections;
import org.json.JSONArray;
import org.json.JSONObject;

public final class LineageCameraInventory {
    public static void main(String[] args) throws Exception {
        if (args.length > 1 || (args.length == 1 && !args[0].equals("--session-keys"))) {
            throw new IllegalArgumentException("Optional argument: --session-keys");
        }
        boolean sessionKeys = args.length == 1;
        Looper.prepare();
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = activityThread.getMethod("systemMain").invoke(null);
        Context context = (Context) activityThread.getMethod("getSystemContext").invoke(thread);
        CameraManager manager = context.getSystemService(CameraManager.class);
        JSONObject report = new JSONObject();
        JSONArray devices = new JSONArray();
        JSONArray publicIds = new JSONArray();
        for (String id : manager.getCameraIdList()) {
            CameraCharacteristics c = manager.getCameraCharacteristics(id);
            JSONObject row = new JSONObject();
            row.put("id", id);
            row.put("facing", c.get(CameraCharacteristics.LENS_FACING));
            Size size = c.get(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE);
            row.put("pixel_width", size == null ? JSONObject.NULL : size.getWidth());
            row.put("pixel_height", size == null ? JSONObject.NULL : size.getHeight());
            JSONArray capabilities = new JSONArray();
            boolean system = false;
            for (int capability : c.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES)) {
                capabilities.put(capability);
                system |= capability == CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_SYSTEM_CAMERA;
            }
            row.put("capabilities", capabilities);
            row.put("system_camera", system);
            if (!system) publicIds.put(id);
            ArrayList<String> physical = new ArrayList<>(c.getPhysicalCameraIds());
            Collections.sort(physical);
            row.put("physical_ids", new JSONArray(physical));
            JSONArray focal = new JSONArray();
            for (float length : c.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)) focal.put((double) length);
            row.put("focal_lengths_mm", focal);
            if (sessionKeys) {
                ArrayList<String> names = new ArrayList<>();
                long vendorId = Long.MAX_VALUE;
                if (c.getAvailableSessionKeys() != null) {
                    for (CaptureRequest.Key<?> key : c.getAvailableSessionKeys()) {
                        names.add(key.getName());
                        if (key.getName().startsWith("com.oplus.")) {
                            vendorId = (Long) key.getClass().getMethod("getVendorId").invoke(key);
                        }
                    }
                }
                Collections.sort(names);
                row.put("session_keys", new JSONArray(names));
                JSONArray tags = new JSONArray();
                Class<?> nativeMetadata = Class.forName("android.hardware.camera2.impl.CameraMetadataNative");
                for (String name : new String[]{"com.oplus.packageName", "com.oplus.is.sdk.camera.package"}) {
                    JSONObject tag = new JSONObject();
                    tag.put("name", name);
                    tag.put("listed_session_key", names.contains(name));
                    try {
                        tag.put("id", nativeMetadata.getMethod("getTag", String.class, long.class)
                                .invoke(null, name, vendorId));
                        tag.put("resolved", true);
                    } catch (ReflectiveOperationException error) {
                        tag.put("resolved", false);
                        Throwable cause = error.getCause();
                        tag.put("error_type", (cause == null ? error : cause).getClass().getName());
                    }
                    tags.put(tag);
                }
                row.put("caller_vendor_tags", tags);
            }
            devices.put(row);
        }
        report.put("devices", devices);
        report.put("non_system_camera2_ids", publicIds);
        report.put("limits", "Metadata queried as engineering root; no device opened, image captured, app permission/exposure or physical lens acceptance.");
        System.out.println(report.toString());
        System.out.flush();
        System.exit(0);
    }
}
