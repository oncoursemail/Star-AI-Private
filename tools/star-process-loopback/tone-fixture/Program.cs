// Disposable, low-amplitude POSITIVE CONTROL ONLY, NOT Star's voice engine.
// Audio is generated in memory and rendered through the default output endpoint.
// No microphone, game, network, OBS, transcripts or file recording.
using System.Buffers.Binary;
using NAudio.Wave;

internal sealed class FiniteTone : IWaveProvider
{
    private const int Rate = 48000;
    private const int Channels = 2;
    private const int TotalFrames = Rate * 2;
    private long _frame;
    public WaveFormat WaveFormat { get; } = new(Rate, 16, Channels);

    public int Read(byte[] buffer, int offset, int count)
    {
        if (buffer is null || offset < 0 || count < 0 ||
            offset > buffer.Length || count > buffer.Length - offset)
            throw new ArgumentException("invalid audio destination");
        int frames = Math.Min(count / (Channels * 2), (int)(TotalFrames - _frame));
        for (int i = 0; i < frames; i++)
        {
            long frame = _frame++;
            double fade = Math.Min(1, Math.Min(frame, TotalFrames - 1 - frame) / 480.0);
            // Peak amplitude is ~0.03 of full scale, with 10ms fade in/out.
            short sample = (short)Math.Round(Math.Sin(2 * Math.PI * 440 * frame / Rate) *
                                             0.03 * fade * short.MaxValue);
            int start = offset + i * Channels * 2;
            BinaryPrimitives.WriteInt16LittleEndian(buffer.AsSpan(start, 2), sample);
            BinaryPrimitives.WriteInt16LittleEndian(buffer.AsSpan(start + 2, 2), sample);
        }
        return frames * Channels * 2;
    }
}

internal static class Program
{
    private static int Main(string[] args)
    {
        if (args is ["--self-test"])
        {
            var tone = new FiniteTone();
            byte[] buffer = new byte[192000];
            int count = tone.Read(buffer, 0, buffer.Length);
            if (count != buffer.Length || tone.WaveFormat.SampleRate != 48000 ||
                tone.WaveFormat.Channels != 2)
                return 1;
            short peak = 0;
            for (int i = 0; i < count; i += 2)
            {
                short x = BinaryPrimitives.ReadInt16LittleEndian(buffer.AsSpan(i, 2));
                peak = (short)Math.Max(peak, Math.Abs((int)x));
            }
            if (peak < 500 || peak > 1100) return 1;
            for (int i = 0; i < 4; ++i) _ = tone.Read(buffer, 0, buffer.Length);
            if (tone.Read(buffer, 0, buffer.Length) != 0) return 1;
            Console.WriteLine("{\"fixture_self_test\":\"pass\",\"audio_playback_started\":false}");
            return 0;
        }
        if (args is not ["--play-test-tone", "--owner-approved"])
        {
            Console.Error.WriteLine("positive tone playback requires exact authorized arguments");
            return 2;
        }
        if (!OperatingSystem.IsWindows()) return 3;
        try
        {
            // Lets the separately launched process-loopback observer activate first.
            Thread.Sleep(600);
            using var player = new WaveOut();
            player.Init(new FiniteTone());
            player.Play();
            Thread.Sleep(2450);
            player.Stop();
            return 0;
        }
        catch (Exception)
        {
            // Do not leak audio endpoint details or owner machine paths.
            Console.Error.WriteLine("dedicated private test-tone output unavailable");
            return 4;
        }
    }
}
