/* Bounded silent playback-path test; no microphone, saved media or volume changes. */
import android.media.AudioAttributes;
import android.media.AudioDeviceInfo;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.os.SystemClock;
import org.json.JSONObject;

public final class LineageAudioPlaybackProbe {
    public static void main(String[] args) throws Exception {
        JSONObject report = new JSONObject();
        AudioTrack track = null;
        try {
            int rate = AudioTrack.getNativeOutputSampleRate(AudioManager.STREAM_MUSIC);
            if (rate <= 0) throw new IllegalStateException("No native output sample rate");
            int frames = rate / 2;
            byte[] silence = new byte[frames * 2];
            track = new AudioTrack.Builder()
                    .setAudioAttributes(new AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_MEDIA)
                            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                    .setAudioFormat(new AudioFormat.Builder().setSampleRate(rate)
                            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                            .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                    .setTransferMode(AudioTrack.MODE_STATIC)
                    .setBufferSizeInBytes(silence.length).build();
            // MODE_STATIC starts as STATE_NO_STATIC_DATA until the first write.
            report.put("state_before_write", track.getState());
            int written = track.write(silence, 0, silence.length);
            report.put("initialized", track.getState() == AudioTrack.STATE_INITIALIZED);
            report.put("sample_rate", rate);
            report.put("expected_frames", frames);
            report.put("written_bytes", written);
            long started = SystemClock.elapsedRealtime();
            track.play();
            while (track.getPlaybackHeadPosition() < frames &&
                    SystemClock.elapsedRealtime() - started < 2000) {
                SystemClock.sleep(20);
            }
            int played = track.getPlaybackHeadPosition();
            AudioDeviceInfo device = track.getRoutedDevice();
            report.put("played_frames", played);
            report.put("elapsed_ms", SystemClock.elapsedRealtime() - started);
            report.put("output_device_type", device == null ? JSONObject.NULL : device.getType());
            report.put("success", track.getState() == AudioTrack.STATE_INITIALIZED &&
                    written == silence.length && played >= frames);
        } catch (Throwable error) {
            report.put("success", false);
            report.put("error_class", error.getClass().getName());
            report.put("error_message", error.getMessage());
        } finally {
            if (track != null) {
                try { track.stop(); } catch (IllegalStateException ignored) { }
                track.release();
            }
        }
        report.put("limits", "Half-second zero-PCM playback and frame delivery only. Does not prove audible speaker quality, microphone, call audio or Bluetooth audio. No volume changes, recording or saved media.");
        System.out.println(report.toString());
        System.out.flush();
        // app_process keeps Binder worker threads alive after main returns.
        System.exit(0);
    }
}
