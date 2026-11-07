/* Three discarded YUV frames per public camera. No pixels read, photos or saved media. */
import android.content.Context;
import android.graphics.ImageFormat;
import android.hardware.camera2.*;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Looper;
import android.util.Size;
import java.util.Arrays;
import java.util.Comparator;
import java.util.Collections;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.*;
import org.json.JSONArray;
import org.json.JSONObject;

public final class LineageCameraFrameProbe {
    private static JSONObject test(CameraManager manager, String id, Size size, Handler handler)
            throws Exception {
        JSONObject row = new JSONObject().put("id", id).put("width", size.getWidth())
                .put("height", size.getHeight());
        AtomicInteger frames = new AtomicInteger();
        AtomicLong last = new AtomicLong();
        AtomicBoolean monotonic = new AtomicBoolean(true), closing = new AtomicBoolean(false);
        AtomicReference<String> error = new AtomicReference<>();
        AtomicReference<CameraDevice> device = new AtomicReference<>();
        AtomicReference<CameraCaptureSession> session = new AtomicReference<>();
        CountDownLatch done = new CountDownLatch(1), closed = new CountDownLatch(1);
        ImageReader reader = ImageReader.newInstance(size.getWidth(), size.getHeight(),
                ImageFormat.YUV_420_888, 2);
        reader.setOnImageAvailableListener(source -> {
            try (Image image = source.acquireLatestImage()) {
                if (image != null && !closing.get()) {
                    long previous = last.getAndSet(image.getTimestamp());
                    if (image.getTimestamp() <= previous) monotonic.set(false);
                    if (frames.incrementAndGet() >= 3) done.countDown();
                }
            } catch (IllegalStateException ignored) { }
        }, handler);
        try {
            manager.openCamera(id, new CameraDevice.StateCallback() {
                public void onOpened(CameraDevice camera) {
                    device.set(camera);
                    if (closing.get()) { camera.close(); return; }
                    try {
                        camera.createCaptureSession(Collections.singletonList(reader.getSurface()),
                                new CameraCaptureSession.StateCallback() {
                            public void onConfigured(CameraCaptureSession configured) {
                                session.set(configured);
                                if (closing.get()) { configured.close(); return; }
                                try {
                                    CaptureRequest.Builder request = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                                    request.addTarget(reader.getSurface());
                                    request.set(CaptureRequest.FLASH_MODE, CaptureRequest.FLASH_MODE_OFF);
                                    configured.setRepeatingRequest(request.build(), null, handler);
                                } catch (Exception failure) {
                                    error.set(failure.getClass().getSimpleName()); done.countDown();
                                }
                            }
                            public void onConfigureFailed(CameraCaptureSession failed) {
                                error.set("session_configuration_failed"); done.countDown();
                            }
                        }, handler);
                    } catch (Exception failure) {
                        error.set(failure.getClass().getSimpleName()); done.countDown();
                    }
                }
                public void onDisconnected(CameraDevice camera) {
                    error.set("camera_disconnected"); done.countDown(); camera.close();
                }
                public void onError(CameraDevice camera, int code) {
                    error.set("camera_error_" + code); done.countDown(); camera.close();
                }
                public void onClosed(CameraDevice camera) { closed.countDown(); }
            }, handler);
            row.put("deadline_completed", done.await(6, TimeUnit.SECONDS));
        } catch (SecurityException denied) {
            error.set("probe_context_permission_denied");
        } catch (CameraAccessException unavailable) {
            error.set("camera_access_reason_" + unavailable.getReason());
        } finally {
            closing.set(true);
            if (session.get() != null) session.get().close();
            if (device.get() != null) {
                device.get().close(); closed.await(1, TimeUnit.SECONDS);
            }
            reader.close();
        }
        row.put("frames", frames.get()).put("timestamps_monotonic", monotonic.get())
                .put("success", frames.get() >= 3 && monotonic.get() && error.get() == null)
                .put("error", error.get() == null ? JSONObject.NULL : error.get());
        return row;
    }

    public static void main(String[] args) throws Exception {
        Looper.prepare();
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = activityThread.getMethod("systemMain").invoke(null);
        Context context = (Context) activityThread.getMethod("getSystemContext").invoke(thread);
        CameraManager manager = context.getSystemService(CameraManager.class);
        HandlerThread worker = new HandlerThread("CameraFrameProbe"); worker.start();
        JSONArray rows = new JSONArray();
        try {
            for (String id : manager.getCameraIdList()) {
                CameraCharacteristics characteristics = manager.getCameraCharacteristics(id);
                boolean system = false;
                for (int capability : characteristics.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES))
                    system |= capability == CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_SYSTEM_CAMERA;
                if (system) continue;
                StreamConfigurationMap map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
                Size[] sizes = map.getOutputSizes(ImageFormat.YUV_420_888);
                if (sizes == null || sizes.length == 0) {
                    rows.put(new JSONObject().put("id", id).put("success", false).put("error", "no_yuv_output"));
                    continue;
                }
                Arrays.sort(sizes, Comparator.comparingLong(size -> (long) size.getWidth() * size.getHeight()));
                Size selected = sizes[0];
                for (Size candidate : sizes) if ((long) candidate.getWidth() * candidate.getHeight() >= 76800) {
                    selected = candidate; break;
                }
                JSONObject row = test(manager, id, selected, new Handler(worker.getLooper())); rows.put(row);
                if ("probe_context_permission_denied".equals(row.optString("error"))) break;
            }
        } finally { worker.quitSafely(); worker.join(1000); }
        System.out.println(new JSONObject().put("cameras", rows).put("limits",
                "Discarded YUV frame delivery only; no pixel contents read or saved, JPEG/video, autofocus, flash or visual-quality proof. Permission/busy failures may be probe context limits.").toString());
        System.out.flush(); System.exit(0);
    }
}
