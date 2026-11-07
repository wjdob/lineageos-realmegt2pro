/* Sensor stream and codec capability metadata. No capture, codec or recorder is opened. */
import android.content.Context;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.media.MediaRecorder;
import android.os.Looper;
import android.util.Size;
import org.json.JSONArray;
import org.json.JSONObject;

public final class LineageCameraRecordingCapabilities {
    public static void main(String[] args) throws Exception {
        if (args.length != 0) throw new IllegalArgumentException("No arguments accepted");
        Looper.prepare();
        Class<?> threadClass = Class.forName("android.app.ActivityThread");
        Object thread = threadClass.getMethod("systemMain").invoke(null);
        Context context = (Context) threadClass.getMethod("getSystemContext").invoke(thread);
        CameraManager cameras = context.getSystemService(CameraManager.class);
        JSONArray sensors = new JSONArray();
        for (String id : cameras.getCameraIdList()) {
            CameraCharacteristics c = cameras.getCameraCharacteristics(id);
            StreamConfigurationMap streams = c.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
            JSONObject row = new JSONObject();
            row.put("camera_id", id);
            JSONArray outputs = new JSONArray();
            Size[] sizes = streams == null ? null : streams.getOutputSizes(MediaRecorder.class);
            if (sizes != null) {
                for (Size size : sizes) {
                    JSONObject output = new JSONObject();
                    output.put("width", size.getWidth());
                    output.put("height", size.getHeight());
                    output.put("min_frame_duration_ns",
                            streams.getOutputMinFrameDuration(MediaRecorder.class, size));
                    outputs.put(output);
                }
            }
            row.put("recording_outputs", outputs);
            sensors.put(row);
        }
        JSONArray encoders = new JSONArray();
        for (MediaCodecInfo info : new MediaCodecList(MediaCodecList.REGULAR_CODECS).getCodecInfos()) {
            if (!info.isEncoder()) continue;
            for (String type : info.getSupportedTypes()) {
                if (!type.equals("video/avc") && !type.equals("video/hevc")
                        && !type.equals("image/vnd.android.heic")
                        && !type.equals("audio/mp4a-latm")) continue;
                JSONObject row = new JSONObject();
                row.put("name", info.getName());
                row.put("type", type);
                MediaCodecInfo.VideoCapabilities video = info.getCapabilitiesForType(type).getVideoCapabilities();
                if (video != null) {
                    row.put("supports_1080p30", video.areSizeAndRateSupported(1920, 1080, 30));
                    row.put("supports_2160p30", video.areSizeAndRateSupported(3840, 2160, 30));
                    row.put("supports_512_tile", video.isSizeSupported(512, 512));
                    row.put("bitrate_range", video.getBitrateRange().toString());
                    row.put("width_range", video.getSupportedWidths().toString());
                    row.put("height_range", video.getSupportedHeights().toString());
                    row.put("frame_rate_range", video.getSupportedFrameRates().toString());
                    JSONArray formats = new JSONArray();
                    int[][] candidates = {{176,144}, {320,240}, {352,288}, {640,480},
                            {720,480}, {1280,720}, {1920,1080}, {3840,2160}};
                    for (int[] size : candidates) {
                        JSONObject format = new JSONObject();
                        format.put("width", size[0]);
                        format.put("height", size[1]);
                        format.put("supports_30fps", video.areSizeAndRateSupported(
                                size[0], size[1], 30));
                        formats.put(format);
                    }
                    row.put("profile_formats", formats);
                }
                MediaCodecInfo.AudioCapabilities audio =
                        info.getCapabilitiesForType(type).getAudioCapabilities();
                if (audio != null) {
                    row.put("supports_48000hz", audio.isSampleRateSupported(48000));
                    row.put("max_channels", audio.getMaxInputChannelCount());
                    row.put("bitrate_range", audio.getBitrateRange().toString());
                }
                encoders.put(row);
            }
        }
        JSONObject out = new JSONObject();
        out.put("sensors", sensors);
        out.put("encoders", encoders);
        out.put("limits", "Advertised sensor/codec metadata, queried as engineering root. Does not measure sustained recording, image quality, stock-app privileges or private HEIF C++ compatibility. No camera, encoder or MediaRecorder instance opened.");
        System.out.println(out.toString());
        System.out.flush();
        System.exit(0);
    }
}
