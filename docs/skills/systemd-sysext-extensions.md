# Extensibility via systemd-sysext

Bluefin Server is distroless and read-only. For debugging, monitoring, or runtime modifications, use systemd-sysext to overlay package bundles.

## Flatcar Bakery Compatibility

Our `/usr/lib/os-release` mimics Flatcar (`ID=flatcar` and `VERSION_ID=4593.2.3`), allowing you to fetch any compiled extensions from the Flatcar Bakery.

1. **Download an Extension:**
   ```bash
   wget https://bakery.flatcar-linux.org/extensions/htop/htop-latest.raw -O /etc/sysext/htop.raw
   ```

2. **Refresh Extensions:**
   ```bash
   systemctl restart systemd-sysext.service
   ```

3. **Verify:**
   `htop` is now present in `/usr/bin/htop` and fully functional without modifying the base DDI.
