/* One second of in-memory PCM; report delivery/aggregate level, never audio contents. */
import android.media.*;
import android.os.SystemClock;
import org.json.JSONObject;

public final class LineageMicrophoneProbe {
    public static void main(String[] args) throws Exception {
        JSONObject result = new JSONObject(); AudioRecord recorder = null;
        short[] buffer = new short[1024];
        try {
            int rate = 16000;
            int minimum = AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT);
            if (minimum <= 0) throw new IllegalStateException("No supported input buffer");
            recorder = new AudioRecord.Builder().setAudioSource(MediaRecorder.AudioSource.MIC)
                    .setAudioFormat(new AudioFormat.Builder().setSampleRate(rate)
                            .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                            .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                    .setBufferSizeInBytes(Math.max(minimum, rate * 2)).build();
            result.put("initialized", recorder.getState() == AudioRecord.STATE_INITIALIZED);
            long start = SystemClock.elapsedRealtime();
            recorder.startRecording(); int samples = 0, nonzero = 0; double energy = 0;
            while (samples < rate && SystemClock.elapsedRealtime() - start < 3000) {
                int count = recorder.read(buffer, 0, buffer.length, AudioRecord.READ_BLOCKING);
                if (count < 0) throw new IllegalStateException("AudioRecord read code " + count);
                for (int index = 0; index < count; index++) {
                    double normalized = buffer[index] / 32768.0;
                    energy += normalized * normalized;
                    if (buffer[index] != 0) nonzero++;
                }
                samples += count;
            }
            AudioDeviceInfo route = recorder.getRoutedDevice();
            result.put("sample_rate", rate).put("samples", samples).put("nonzero_samples", nonzero)
                    .put("rms", samples == 0 ? 0 : Math.sqrt(energy / samples))
                    .put("input_device_type", route == null ? JSONObject.NULL : route.getType())
                    .put("success", recorder.getState() == AudioRecord.STATE_INITIALIZED && samples >= rate);
        } catch (Throwable failure) {
            result.put("success", false).put("error_class", failure.getClass().getName())
                    .put("error_message", failure.getMessage());
        } finally {
            java.util.Arrays.fill(buffer, (short) 0);
            if (recorder != null) {
                try { recorder.stop(); } catch (IllegalStateException ignored) { }
                recorder.release();
            }
        }
        result.put("limits", "Default microphone path/sample delivery and aggregate level only. No raw audio saved, transcription, voice-quality, other microphones or call-audio proof. Permission/context failures are not hardware failures.");
        System.out.println(result.toString()); System.out.flush(); System.exit(0);
    }
}
