/* Microphone capture for the live voice (2026-11-02): runs off the main thread,
   averages the device rate down to 16 kHz mono, and posts 80 ms frames of
   signed 16-bit PCM with their level (RMS). Loaded with addModule from the
   same origin, so the page's CSP needs no change. */
const OUT_RATE = 16000;
const FRAME = 1280;                       // 80 ms at 16 kHz

class MeghPcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / OUT_RATE;
    this.pos = 0;
    this.sum = 0;
    this.cnt = 0;
    this.buf = new Int16Array(FRAME);
    this.n = 0;
    this.sq = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.sum += ch[i];
      this.cnt += 1;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        let v = this.sum / this.cnt;
        if (v > 1) v = 1; else if (v < -1) v = -1;
        this.sq += v * v;
        this.buf[this.n++] = v < 0 ? v * 32768 : v * 32767;
        this.sum = 0;
        this.cnt = 0;
        if (this.n === FRAME) {
          const rms = Math.sqrt(this.sq / FRAME);
          this.port.postMessage({ pcm: this.buf.buffer, rms }, [this.buf.buffer]);
          this.buf = new Int16Array(FRAME);
          this.n = 0;
          this.sq = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor('megh-pcm-capture', MeghPcmCapture);
