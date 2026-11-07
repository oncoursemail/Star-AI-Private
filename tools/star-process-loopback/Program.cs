// Bounded, owner-invoked Windows process-loopback diagnostic.
// Does not write PCM, access a microphone, claim silence, or authorize a stream.
// A future trusted host MUST independently pin process identity, callback health,
// pending native packets and physical stop before treating this as a witness.
using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.RegularExpressions;
using NAudio.Wave;
using NAudio.CoreAudioApi;

internal static class Program
{
    private sealed record Options(int Pid, string ExpectedExe, int DurationMs);

    private static readonly Regex ExeName = new(
        @"\A[A-Za-z0-9][A-Za-z0-9_. -]{0,79}\.exe\z",
        RegexOptions.CultureInvariant | RegexOptions.IgnoreCase);

    private static long _callbacks;
    private static long _frames;
    private static long _badPackets;
    private static long _lastPacketTicks;
    private static int _peakMilli;

    private static Options Parse(string[] args)
    {
        if (args.Length != 7 || args[0] != "--observe")
            throw new ArgumentException("expected --observe --pid N --expect-exe Voice.exe --duration-ms N");
        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        for (int i = 1; i < args.Length; i += 2)
        {
            if (!new[] { "--pid", "--expect-exe", "--duration-ms" }.Contains(args[i]) ||
                !values.TryAdd(args[i], args[i + 1]))
                throw new ArgumentException("unknown or duplicate parameter");
        }
        if (!values.TryGetValue("--pid", out var pidValue) ||
            !values.TryGetValue("--expect-exe", out var exe) ||
            !values.TryGetValue("--duration-ms", out var durationValue) ||
            !int.TryParse(pidValue, NumberStyles.None, CultureInfo.InvariantCulture, out int pid) ||
            pid < 1 || pid > int.MaxValue - 1 ||
            !ExeName.IsMatch(exe) ||
            !int.TryParse(durationValue, NumberStyles.None, CultureInfo.InvariantCulture, out int duration) ||
            duration < 300 || duration > 5000)
            throw new ArgumentException("invalid bounded process-loopback arguments");
        return new Options(pid, exe, duration);
    }

    private static void Emit(string state, long elapsedMs = 0)
    {
        long last = Volatile.Read(ref _lastPacketTicks);
        long age = last == 0 ? -1L :
            Math.Max(0L, (long)Stopwatch.GetElapsedTime(last).TotalMilliseconds);
        // No process identifiers, filenames, audio bytes, transcripts, paths or keys.
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            schema = "star.process_loopback.diagnostic.v1",
            state,
            elapsed_ms = elapsedMs,
            callback_generation = Interlocked.Read(ref _callbacks),
            sample_frames = Interlocked.Read(ref _frames),
            bad_packets = Interlocked.Read(ref _badPackets),
            max_peak_milli = Volatile.Read(ref _peakMilli),
            last_callback_age_ms = age,
            verified_silence = false,
            gameplay_authorized = false,
            broadcast_authorized = false
        }));
    }

    private static void AcceptPacket(ReadOnlySpan<byte> buffer)
    {
        if (buffer.Length == 0 || buffer.Length % (sizeof(float) * 2) != 0)
        {
            Interlocked.Increment(ref _badPackets);
            return;
        }
        ReadOnlySpan<float> samples = MemoryMarshal.Cast<byte, float>(buffer);
        int peak = 0;
        foreach (float sample in samples)
        {
            if (!float.IsFinite(sample))
            {
                Interlocked.Increment(ref _badPackets);
                return;
            }
            peak = Math.Max(peak, (int)MathF.Min(1000.0f, MathF.Abs(sample) * 1000.0f));
        }
        int old;
        do
        {
            old = Volatile.Read(ref _peakMilli);
            if (peak <= old) break;
        } while (Interlocked.CompareExchange(ref _peakMilli, peak, old) != old);
        Interlocked.Add(ref _frames, samples.Length / 2);
        Volatile.Write(ref _lastPacketTicks, Stopwatch.GetTimestamp());
        Interlocked.Increment(ref _callbacks);
    }

    private static bool SameProcess(Process process, DateTime originalStartUtc, string expectedExe)
    {
        try
        {
            return !process.HasExited &&
                string.Equals(process.ProcessName + ".exe", expectedExe,
                    StringComparison.OrdinalIgnoreCase) &&
                process.StartTime.ToUniversalTime() == originalStartUtc;
        }
        catch
        {
            return false;
        }
    }

    private static int SelfTest()
    {
        try
        {
            var valid = Parse(new[] {
                "--observe", "--pid", "42", "--expect-exe", "StarVoice.exe", "--duration-ms", "400"
            });
            if (valid.Pid != 42 || valid.DurationMs != 400) return 1;
            string[][] bad = [
                [], ["--pid", "42"], ["--observe", "--pid", "0", "--expect-exe",
                    "StarVoice.exe", "--duration-ms", "400"],
                ["--observe", "--pid", "42", "--expect-exe",
                    "../voice.exe", "--duration-ms", "400"],
                ["--observe", "--pid", "42", "--expect-exe",
                    "StarVoice.exe", "--duration-ms", "60000"],
                ["--observe", "--pid", "42", "--pid",
                    "43", "--duration-ms", "400"]
            ];
            foreach (var attempt in bad)
            {
                try { _ = Parse(attempt); return 1; }
                catch (ArgumentException) { }
            }
            AcceptPacket(MemoryMarshal.AsBytes(new float[] { -0.5f, 0.25f, 0f, 0.75f }.AsSpan()));
            if (Interlocked.Read(ref _callbacks) != 1 || Interlocked.Read(ref _frames) != 2 ||
                Volatile.Read(ref _peakMilli) != 750 || Volatile.Read(ref _lastPacketTicks) == 0)
                return 1;
            AcceptPacket(MemoryMarshal.AsBytes(new float[] { float.NaN, 0f }.AsSpan()));
            if (Interlocked.Read(ref _badPackets) != 1 || Interlocked.Read(ref _callbacks) != 1)
                return 1;
            Console.WriteLine("{\"self_test\":\"pass\",\"capture_started\":false}");
            return 0;
        }
        catch { return 1; }
    }

    private static async Task<int> Main(string[] args)
    {
        if (args.Length == 1 && args[0] == "--self-test") return SelfTest();
        Options options;
        try { options = Parse(args); }
        catch (ArgumentException)
        {
            Console.Error.WriteLine("invalid argument or missing explicit --observe");
            return 2;
        }
        // Explicit owner invocation is necessary but does not authenticate a remote caller.
        if (!OperatingSystem.IsWindows() || Environment.OSVersion.Version.Build < 20348)
        {
            Console.Error.WriteLine("Windows 10 build 20348+ required");
            return 3;
        }
        try
        {
            using Process target = Process.GetProcessById(options.Pid);
            DateTime pinnedStart = target.StartTime.ToUniversalTime();
            if (!SameProcess(target, pinnedStart, options.ExpectedExe))
            {
                Console.Error.WriteLine("target process identity unavailable or changed");
                return 4;
            }
            await using var recorder = await new WasapiRecorderBuilder()
                .WithProcessLoopback((uint)options.Pid, ProcessLoopbackMode.IncludeTargetProcessTree)
                .WithFormat(WaveFormat.CreateIeeeFloatWaveFormat(48000, 2))
                .BuildAsync();
            recorder.DataAvailable += (buffer, _, _, _) => AcceptPacket(buffer);
            recorder.StartRecording();
            var clock = Stopwatch.StartNew();
            Emit("capture_started");
            while (clock.ElapsedMilliseconds < options.DurationMs)
            {
                await Task.Delay(50);
                if (!SameProcess(target, pinnedStart, options.ExpectedExe) ||
                    Volatile.Read(ref _badPackets) != 0)
                {
                    recorder.StopRecording();
                    Emit("capture_invalid", clock.ElapsedMilliseconds);
                    return 4;
                }
                Emit("observing_no_silence_claim", clock.ElapsedMilliseconds);
            }
            recorder.StopRecording();
            Emit("capture_complete_no_silence_claim", clock.ElapsedMilliseconds);
            return 0;
        }
        catch (Exception)
        {
            // Do not expose exception strings: OS paths and device identities are private.
            Console.Error.WriteLine("local process-loopback capture unavailable");
            return 5;
        }
    }
}
