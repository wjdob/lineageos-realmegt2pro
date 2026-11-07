/* One bounded public HTTPS connectivity check; no settings, cookies or user payload. */
import java.net.InetAddress;
import java.net.URL;
import javax.net.ssl.HttpsURLConnection;
import android.os.SystemClock;
import org.json.JSONObject;

public final class LineageNetworkProbe {
    public static void main(String[] args) throws Exception {
        JSONObject report = new JSONObject();
        HttpsURLConnection connection = null;
        long started = SystemClock.elapsedRealtime();
        try {
            String host = "connectivitycheck.gstatic.com";
            report.put("dns_address_count", InetAddress.getAllByName(host).length);
            connection = (HttpsURLConnection) new URL("https://" + host + "/generate_204").openConnection();
            connection.setConnectTimeout(5000);
            connection.setReadTimeout(5000);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setRequestProperty("User-Agent", "LineageCoreProbe/1");
            int status = connection.getResponseCode();
            report.put("http_status", status);
            report.put("success", status == 204);
        } catch (Throwable error) {
            report.put("success", false);
            report.put("error_class", error.getClass().getName());
            report.put("error_message", error.getMessage());
        } finally {
            if (connection != null) connection.disconnect();
        }
        report.put("elapsed_ms", SystemClock.elapsedRealtime() - started);
        report.put("limits", "One public DNS/HTTPS204 check using the probe UID's default route. Not a per-app VPN, cellular-only, call, SMS or IMS test. No user payload, cookies or settings changes.");
        System.out.println(report.toString());
        System.out.flush();
        System.exit(0);
    }
}
