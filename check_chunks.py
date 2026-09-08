from pymongo import MongoClient
import certifi, os
from dotenv import load_dotenv
from collections import Counter
import statistics

load_dotenv("configs/.env")
col = MongoClient(
    os.getenv("MONGO_URI"),
    tlsCAFile=certifi.where(),
    tlsAllowInvalidCertificates=True,
    tls=True
)["Adv_Ind_Switch"]["EKI_DataSheet_Chunks"]

# chunk counts per model
counts = Counter(d["model_name"] for d in col.find({}, {"model_name": 1}))
print("=== All models with chunk counts ===")
for k, v in sorted(counts.items()):
    print("  %s: %d" % (k, v))

# content length stats
lengths = [len(d.get("content", "")) for d in col.find({}, {"content": 1})]
print("\n=== Content length ===")
print("  min=%d  max=%d  avg=%d  median=%d" % (
    min(lengths), max(lengths),
    round(statistics.mean(lengths)),
    round(statistics.median(lengths))
))

# sample chunk
print("\n=== Sample EKI chunk ===")
for doc in col.find({}).skip(200).limit(1):
    print("model_name:", doc.get("model_name"))
    print("chunk_id:", doc.get("chunk_id"))
    print("file_source:", doc.get("file_source"))
    print("content:\n", doc["content"][:600])

# check encoding issue - find chunk with garbled text
print("\n=== Garbled content check (first 3) ===")
for doc in col.find({}).limit(3):
    c = doc["content"]
    garbled = any(ord(ch) > 0x4000 and ord(ch) < 0xA000 for ch in c[:50])
    print("  %s | garbled=%s | preview: %s" % (doc["chunk_id"], garbled, c[:80]))
