# TPM2 Credential Sealing

To secure sensitive provisioning credentials (such as hashed root passwords or SSH keys) against physical tampering or unauthorized extraction:

1. **Verify TPM2 Device Availability:**
   ```bash
   systemd-creds list
   ```

2. **Encrypt and Seal Credential:**
   Seal the credential against PCR 7 (Secure Boot state) and PCR 11 (Unified Kernel Image state) of the TPM2 chip:
   ```bash
   systemd-creds encrypt \
     --name=passwd.hashed-password.root \
     --seal \
     --pcr-ids=7+11 \
     /path/to/plaintext_password_hash.txt \
     /path/to/secured_credential.cred
   ```

3. **Provide Encrypted Credential to Live Host:**
   Pass the output `.cred` file to the node via ESP (`/loader/credentials/passwd.hashed-password.root.cred`) or container argument `--set-credential`.
