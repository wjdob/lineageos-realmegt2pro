/* Drop this diagnostic process to the UID matching Android's system Context. */
public final class LineageSystemGnssLauncher {
    public static void main(String[] args) throws Exception {
        if (android.os.Process.myUid() == 0) {
            android.system.Os.setgid(1000);
            android.system.Os.setuid(1000);
        }
        if (android.os.Process.myUid() != 1000)
            throw new SecurityException("GNSS system-context probe requires matching UID 1000");
        System.err.println("Diagnostic child UID=" + android.os.Process.myUid());
        LineageGnssProbe.main(args);
    }
}
