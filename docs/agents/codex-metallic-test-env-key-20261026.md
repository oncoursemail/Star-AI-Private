# Metallic test-cache environment values

Changing a configured test variable, such as `FEATURE=0` to `FEATURE=1`, previously kept the same test-cache key because `test_key` hashed only the mapping's names. A cached pass could then suppress a run under different settings. The key now hashes sorted name/value pairs. Dictionary insertion order remains immaterial, and actual environment values are not printed by this check.

The standalone `scripts/verify_metallic_test_env_key.py` exercises changed values, reordered mappings, explicit empty values, stable settings, additional variables, value boundaries and an actual temporary cache across restart. It proves the changed key cannot retrieve the earlier pass. It does not run project commands, edit harness fixtures or change evaluation gates. Only explicitly configured test environment values are covered; this patch does not claim to fingerprint every inherited process variable.
