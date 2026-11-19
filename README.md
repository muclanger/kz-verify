# kz-verify

Free, open-source verifier for the AI labelling that Tom Langer applies to content made with his own local AI systems (EU AI Act, Art. 50(2): machine-readable marking and detectability).

Everything runs locally. No file is uploaded anywhere.

## What is marked, and how

Every published or delivered file that contains AI-generated material from these systems carries two independent markings.

**1. Invisible watermark in the content**

| Media | Method | Parameters | Payload |
|---|---|---|---|
| Images | [Adobe TrustMark](https://github.com/adobe/trustmark) (MIT) | variant **P**, ECC schema **0** (BCH_SUPER, 40 bit) | random id |
| Speech | [Meta AudioSeal](https://github.com/facebookresearch/audioseal) (MIT), v0.2.1 | 16-bit model; marked when ≥ 50 % of 16 kHz frames score above 0.5 (whole file or best 4-s window) | random 16-bit message |

Detection rules that matter for a correct result:

- TrustMark reads its ECC schema from the picture. Only **schema 0** is ours; detections in other schemas are noise and must be ignored.
- If an image shows nothing, try once more after cropping away a flat border (e.g. a card shared on a story background).
- AudioSeal is run on 2-second chunks (one long call is very slow on CPU); results are combined per frame.

**2. Signed C2PA manifest** ([Content Credentials](https://c2pa.org))

- Action `c2pa.created` with the IPTC digital source type: `trainedAlgorithmicMedia`, `compositeSynthetic` or `compositeWithTrainedAlgorithmicMedia`.
- Images: soft binding `com.adobe.trustmark.P` pointing to the watermark, action `c2pa.watermarked.bound`.
- Audio: action `c2pa.watermarked.unbound`; the watermark bits are in the assertion `de.tom-langer.kz`.
- Signed with the certificate "kz Content Credentials", issued by **Tom Langer kz Root CA**, timestamped by DigiCert's TSA.
- The root is not on the C2PA trust list, so general tools show "issuer not recognized". The root certificate is included here (`src/kz_verify/anchors/tom-langer-kz-root.pem`):

  ```
  SHA-256 fingerprint: 16ea94869c99d8bf284e216a310d21392e16d1a8297d4ab2dfcd43dbd4762ed0
  ```

Neither marking contains personal data. Social platforms usually remove the manifest on upload; the watermark is designed to remain.

## Check a file

```bash
pip install git+https://github.com/muclanger/kz-verify   # or: pip install .  (in a clone)
kz-verify picture.png
kz-verify voice.wav --json
```

On Windows, set `PYTHONUTF8=1` before installing (PowerShell: `$env:PYTHONUTF8="1"`); TrustMark's setup otherwise fails to read its own README. A CPU-only PyTorch is enough (`--index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple`).

For layer 2, [c2patool](https://github.com/contentauth/c2patool) must be on `PATH` (or pass `--c2patool PATH`). Without it, kz-verify checks the watermark only. MP3/M4A need `ffmpeg`. Model weights are downloaded once from Adobe (TrustMark) and Hugging Face (AudioSeal).

Exit code `0` = AI marking found, `1` = none found.

Other free ways to check:

- C2PA: `c2patool <file>`, the CAI [Verify](https://verify.contentauthenticity.org/) site or Adobe's [Inspect](https://contentauthenticity.adobe.com/inspect) tool.
- Watermarks: the reference decoders in the TrustMark and AudioSeal repositories with the parameters above.

## Please do not remove the markings

The markings exist so that anyone can recognise AI-generated content. Removing, altering or forging them is not permitted.

## Deutsch

`kz-verify` prüft kostenlos und lokal, ob eine Datei die KI-Kennzeichnung von Tom Langer trägt (Art. 50 Abs. 2 KI-Verordnung). Geprüft werden zwei Ebenen: das unsichtbare Wasserzeichen (Bilder: Adobe TrustMark P, Schema 0; Sprache: Meta AudioSeal 16 Bit) und das signierte C2PA-Manifest (ausgestellt von „Tom Langer kz Root CA“, Fingerabdruck oben). Beide enthalten keine personenbezogenen Daten. Plattformen entfernen das Manifest meist beim Hochladen, das Wasserzeichen bleibt. Die Markierungen dürfen nicht entfernt oder verfälscht werden.

## License

MIT, see `LICENSE`. TrustMark and AudioSeal are MIT-licensed by Adobe and Meta.
