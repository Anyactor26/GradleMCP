package demo;
public final class SmokeTest {
    public static void main(String[] args) {
        if (!Hello.message().equals("Hello from GradleMCP")) {
            throw new AssertionError("Unexpected greeting");
        }
        System.out.println("Smoke test passed");
    }
}
