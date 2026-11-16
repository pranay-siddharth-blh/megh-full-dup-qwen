"""fdx: Mitra's sovereign full-duplex voice pipeline.

browser  <-- the unchanged /ws/live contract -->  fdx.relay  <-- PersonaPlex / Moshi protocol --> duplex core
                                                     |      <-- Kyutai STT protocol ----------> live transcript
                                                     +-- dispatch: Mitra's own brain, tools, SQL, guard
The core hears and speaks at once; the transcript drives Mitra's deterministic layer; results are forced into the
core so it says them in its own voice; a floor controller and a speech firewall decide which of the core's own
words may reach the person. Every number comes from SQL, never from a model."""
