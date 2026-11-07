/* Encoder-profile metadata only. Never opens a camera, codec or recorder. */
import android.media.CamcorderProfile;
import org.json.JSONArray;
import org.json.JSONObject;

public final class LineageCamcorderProfileProbe {
    public static void main(String[] args) throws Exception {
        if (args.length != 0) throw new IllegalArgumentException("No arguments accepted");
        int[] qualities = {CamcorderProfile.QUALITY_LOW, CamcorderProfile.QUALITY_HIGH,
                CamcorderProfile.QUALITY_480P, CamcorderProfile.QUALITY_720P,
                CamcorderProfile.QUALITY_1080P, CamcorderProfile.QUALITY_2160P};
        JSONArray rows = new JSONArray();
        for (int camera = 0; camera <= 4; camera++) {
            for (int quality : qualities) {
                JSONObject row = new JSONObject();
                row.put("camera_id", camera);
                row.put("quality", quality);
                boolean exists = CamcorderProfile.hasProfile(camera, quality);
                row.put("has_profile", exists);
                if (exists || (camera == 1 && quality == CamcorderProfile.QUALITY_1080P)) {
                    try {
                        CamcorderProfile profile = CamcorderProfile.get(camera, quality);
                        row.put("width", profile.videoFrameWidth);
                        row.put("height", profile.videoFrameHeight);
                        row.put("fps", profile.videoFrameRate);
                        row.put("video_codec", profile.videoCodec);
                        row.put("audio_codec", profile.audioCodec);
                    } catch (RuntimeException failure) {
                        row.put("exception", failure.getClass().getName());
                        row.put("message", failure.getMessage());
                    }
                }
                rows.put(row);
            }
        }
        JSONObject out = new JSONObject();
        out.put("profiles", rows);
        out.put("limits", "Global native CamcorderProfile metadata and one known failed lookup. Does not encode media or establish sensor/codec support for advertised dimensions/rates.");
        System.out.println(out.toString());
        System.out.flush();
        System.exit(0);
    }
}
