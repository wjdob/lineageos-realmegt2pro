/* Public MediaCodec metadata/configuration probe. Does not start a codec or read media. */
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.media.MediaFormat;
import org.json.JSONArray;
import org.json.JSONObject;

public final class LineageCodecProbe {
    public static void main(String[] args) throws Exception {
        String action = args.length == 0 ? "inspect" : args[0];
        if (!action.equals("inspect") && !action.equals("c2.android.aac.encoder")
                && !action.equals("c2.qti.aac.hw.encoder")) {
            throw new IllegalArgumentException("Use inspect or an explicitly supported AAC encoder");
        }
        JSONObject result = new JSONObject();
        result.put("action", action);
        result.put("limits", "Metadata or configure/release only; no codec start, media input, "
                + "recording, playback, service restart, policy or persistent setting change. "
                + "A faulty codec provider may fail during configuration. Exit status alone "
                + "does not establish successful configuration or encode/decode operation.");
        if (action.equals("inspect")) {
            JSONArray codecs = new JSONArray();
            for (MediaCodecInfo info : new MediaCodecList(MediaCodecList.ALL_CODECS).getCodecInfos()) {
                if (!info.getName().contains("aac")) continue;
                JSONObject codec = new JSONObject();
                codec.put("name", info.getName());
                codec.put("encoder", info.isEncoder());
                codec.put("hardware", info.isHardwareAccelerated());
                codec.put("types", new JSONArray(info.getSupportedTypes()));
                codecs.put(codec);
            }
            result.put("codecs", codecs);
        } else {
            MediaCodec codec = null;
            result.put("configured", false);
            result.put("released", false);
            try {
                codec = MediaCodec.createByCodecName(action);
                MediaFormat format = MediaFormat.createAudioFormat("audio/mp4a-latm", 48000, 2);
                format.setInteger(MediaFormat.KEY_BIT_RATE, 128000);
                format.setInteger(MediaFormat.KEY_AAC_PROFILE,
                        MediaCodecInfo.CodecProfileLevel.AACObjectLC);
                codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
                result.put("configured", true);
            } catch (Exception error) {
                result.put("error_class", error.getClass().getName());
                result.put("error", error.toString());
            } finally {
                if (codec != null) {
                    try {
                        codec.release();
                        result.put("released", true);
                    } catch (Exception error) {
                        result.put("release_error", error.toString());
                    }
                }
            }
        }
        System.out.println(result.toString());
        System.out.flush();
        System.exit(0);
    }
}
