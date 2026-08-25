| Method | Path | Request body | Response body |
| --- | --- | --- | --- |
| POST | `/api/simulation/start` | `{ "run_label": string }` | `{ "run_id": uuid }` |
| POST | `/api/simulation/attack` | `{ "run_id": uuid, "attack_type": "sybil_flood"\|"collusion_ring"\|"whitewash_return" }` | `{ "ring_id": uuid }` |
| POST | `/api/simulation/reset` | `{ "run_id": uuid }` | `{ "status": "reset" }` |
| GET | `/api/simulation/{run_id}/status` | no body | `{ "tick": int, "status": string, "mode": string }` |
| GET | `/api/metrics/{run_id}/live?mode=hybrid` | no body | latest `metrics_snapshots` row as JSON |
| GET | `/api/metrics/{run_id}/scorecard` | no body | `{ "sybil_flood": {"baseline": float, "hybrid": float}, "collusion_ring": {...}, "whitewash_return": {...} }` |
| GET | `/api/clusters/{cluster_id}/evidence` | no body | `{ "cluster": {...}, "members": [account...], "detections": [...], "pqc_proofs": [...] }` |
| POST | `/api/pqc/demo-forge` | `{ "run_id": uuid, "transaction_id": uuid }` | `{ "verified": false, "proof_id": uuid }` |

CORS: FastAPI must allow the Lovable preview + published domain origins explicitly, and the eventual `/frontend` dev/deploy origin explicitly, no wildcard.
