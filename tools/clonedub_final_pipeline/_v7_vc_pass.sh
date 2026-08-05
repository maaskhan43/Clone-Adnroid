set -a; [ -f ~/.clonedub.env ] && . ~/.clonedub.env; set +a
cd /mnt/d/CloneDub/seed-vc
W=/mnt/d/CloneDub/work/v12_3min_1470_1650
OUT=$W/generated_wavs_v7_vc; mkdir -p $OUT
PY=/mnt/d/CloneDub/seedvc_venv/bin/python
# best clean picks: vid:cand:actor triplets generated from v7_clean_best + lines_v5
python3 - <<PYEOF > /tmp/vc_list.txt
import json
W="/mnt/d/CloneDub/work/v12_3min_1470_1650"
best=json.load(open(W+"/v7_clean_best.json"))
D=json.load(open(W+"/lines_v5.json",encoding="utf-8"))
act={L["vid"]:L["actor"] for L in D["lines"]}
for vid,c in sorted(best.items(),key=lambda x:int(x[0])):
    print("%s %d %s"%(vid,c["cand"],act[int(vid)]))
PYEOF
cat /tmp/vc_list.txt
while read vid cand actor; do
  SRC=$W/generated_wavs_v7_clean/V$(printf %02d $vid)_c${cand}.wav
  TGT=$W/orig_voice_refs_v6/ref_${actor}.wav
  echo "=== V$vid -> $actor ==="
  "$PY" inference.py --source "$SRC" --target "$TGT" --output "$OUT" --diffusion-steps 30 --length-adjust 1.0 --inference-cfg-rate 0.7 --f0-condition False 2>&1 | grep -viE "warn|deprecat" | tail -2
  # rename latest produced file to stable name
  NEW=$(ls -t "$OUT" | head -1)
  mv "$OUT/$NEW" "$OUT/V$(printf %02d $vid).wav"
done < /tmp/vc_list.txt
echo "V7_VC_DONE"
