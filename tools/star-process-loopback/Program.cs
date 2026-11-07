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

    // Per-interval activity is a diagnostic only. A zero-callback interval
    // means *missing PCM observation*, never confirmed digital or physical silence.
    // Capture callbacks never block on disk I/O or console output.
    private static readonly object WindowGate = new();
    private static long _windowStartTicks = Stopwatch.GetTimestamp();
    private static long _windowCallbacks;
    private static long _windowFrames;
    private static long _windowSamples;
    private static double _windowSumSquares;
    private static int _windowPeakMilli;

    private sealed record ActivityWindow(
        long SpanMs, long Callbacks, long Frames, int? PeakMilli, int? RmsMilli);

    // Capture the current interval and cumulative counters *under one lock*.
    // Otherwise a native audio callback between TakeActivityWindow() and
    // Interlocked.Read() could make a valid JSON interval contradict its totals.
    // The external rehearsal verifier requires coherent deltas.
    private sealed record ActivitySnapshot(
        ActivityWindow Window, long TotalCallbacks, long TotalFrames,
        int MaxPeakMilli, long LastPacketTicks);

    private static ActivitySnapshot TakeActivitySnapshot()
    {
        lock (WindowGate)
        {
            long now = Stopwatch.GetTimestamp();
            long span = Math.Max(0L, (long)Stopwatch.GetElapsedTime(_windowStartTicks, now).TotalMilliseconds);
            int? peak = _windowSamples > 0 ? _windowPeakMilli : null;
            int? rms = _windowSamples > 0
                ? (int)Math.Clamp(Math.Round(Math.Sqrt(_windowSumSquares / _windowSamples) * 1000.0), 0, 1000)
                : null;
            var result = new ActivitySnapshot(
                new ActivityWindow(span, _windowCallbacks, _windowFrames, peak, rms),
                Interlocked.Read(ref _callbacks), Interlocked.Read(ref _frames),
                Volatile.Read(ref _peakMilli), Volatile.Read(ref _lastPacketTicks));
            _windowStartTicks = now;
            _windowCallbacks = 0;
            _windowFrames = 0;
            _windowSamples = 0;
            _windowSumSquares = 0;
            _windowPeakMilli = 0;
            return result;
        }
    }

    private static ActivityWindow TakeActivityWindow() => TakeActivitySnapshot().Window;

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
        ActivitySnapshot snapshot = TakeActivitySnapshot();
        ActivityWindow activity = snapshot.Window;
        long last = snapshot.LastPacketTicks;
        long age = last == 0 ? -1L :
            Math.Max(0L, (long)Stopwatch.GetElapsedTime(last).TotalMilliseconds);
        // No process identifiers, filenames, audio bytes, transcripts, paths or keys.
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            schema = "star.process_loopback.diagnostic.v1",
            state,
            elapsed_ms = elapsedMs,
            callback_generation = snapshot.TotalCallbacks,
            sample_frames = snapshot.TotalFrames,
            bad_packets = Interlocked.Read(ref _badPackets),
            max_peak_milli = snapshot.MaxPeakMilli,
            last_callback_age_ms = age,
            activity_window_ms = activity.SpanMs,
            activity_callbacks = activity.Callbacks,
            activity_sample_frames = activity.Frames,
            // Null means no PCM samples arrived, NOT a zero-volume reading.
            activity_peak_milli = activity.PeakMilli,
            activity_rms_milli = activity.RmsMilli,
            activity_is_audio_observation_only = true,
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
        double squares = 0;
        foreach (float sample in samples)
        {
            if (!float.IsFinite(sample))
            {
                Interlocked.Increment(ref _badPackets);
                return;
            }
            float magnitude = MathF.Min(1.0f, MathF.Abs(sample));
            peak = Math.Max(peak, (int)(magnitude * 1000.0f));
            squares += (double)magnitude * magnitude;
        }
        lock (WindowGate)
        {
            _windowCallbacks++;
            _windowFrames += samples.Length / 2;
            _windowSamples += samples.Length;
            _windowSumSquares += squares;
            _windowPeakMilli = Math.Max(_windowPeakMilli, peak);
            if (peak > _peakMilli)
                Volatile.Write(ref _peakMilli, peak);
            // Keep cumulative counters no older than their corresponding
            // interval bucket, even when Emit races with the audio callback.
            Interlocked.Add(ref _frames, samples.Length / 2);
            Volatile.Write(ref _lastPacketTicks, Stopwatch.GetTimestamp());
            Interlocked.Increment(ref _callbacks);
        }
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
            ActivitySnapshot snapshot = TakeActivitySnapshot();
            ActivityWindow activity = snapshot.Window;
            if (snapshot.TotalCallbacks != 1 || snapshot.TotalFrames != 2 ||
                snapshot.MaxPeakMilli != 750 || snapshot.LastPacketTicks == 0 ||
                activity.Callbacks != 1 || activity.Frames != 2 ||
                activity.PeakMilli != 750 || activity.RmsMilli != 468)
                return 1;
            ActivityWindow empty = TakeActivityWindow();
            if (empty.Callbacks != 0 || empty.Frames != 0 ||
                empty.PeakMilli is not null || empty.RmsMilli is not null)
                return 1;
            AcceptPacket(MemoryMarshal.AsBytes(new float[] { float.NaN, 0f }.AsSpan()));
            if (Interlocked.Read(ref _badPackets) != 1 || Interlocked.Read(ref _callbacks) != 1)
                return 1;
            ActivityWindow invalid = TakeActivityWindow();
            if (invalid.Callbacks != 0 || invalid.RmsMilli is not null)
                return 1;

            // Deterministically test the accounting invariant under concurrent
            // packet ingestion. It used to be possible for Emit() to observe
            // a new cumulative callback after resetting the activity bucket.
            // No OS/device capture is started for this synthetic stress test.
            long previousCallbacks = Interlocked.Read(ref _callbacks);
            long previousFrames = Interlocked.Read(ref _frames);
            byte[] synthetic = MemoryMarshal.AsBytes(
                new float[] { 0.1f, -0.2f }.AsSpan()).ToArray();
            var writer = Task.Run(() =>
            {
                for (int i = 0; i < 2048; ++i)
                    AcceptPacket(synthetic);
            });
            for (int i = 0; i < 2048; ++i)
            {
                ActivitySnapshot concurrent = TakeActivitySnapshot();
                if (concurrent.TotalCallbacks - previousCallbacks != concurrent.Window.Callbacks ||
                    concurrent.TotalFrames - previousFrames != concurrent.Window.Frames)
                    return 1;
                previousCallbacks = concurrent.TotalCallbacks;
                previousFrames = concurrent.TotalFrames;
            }
            writer.GetAwaiter().GetResult();
            ActivitySnapshot trailing = TakeActivitySnapshot();
            if (trailing.TotalCallbacks - previousCallbacks != trailing.Window.Callbacks ||
                trailing.TotalFrames - previousFrames != trailing.Window.Frames ||
                trailing.TotalCallbacks != 2049 || trailing.TotalFrames != 2050)
                return 1;
            Console.WriteLine("{\"self_test\":\"pass\",\"capture_started\":false,\"activity_window_tested\":true,\"missing_pcm_means_unknown\":true,\"atomic_activity_windows_tested\":true}");
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
            _ = TakeActivityWindow(); // Reset at owner-invoked recording start.
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
