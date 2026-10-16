"""Editor tokens stay in the operating system vault, never in its outbox."""
import hashlib
import sys


class SessionVault:
    service = "com.scrapdnb.substance.online"

    def _backend(self):
        if sys.platform == "darwin":
            from keyring.backends.macOS import Keyring
            return Keyring()
        if sys.platform == "win32":
            from keyring.backends.Windows import WinVaultKeyring
            return WinVaultKeyring()
        raise RuntimeError("Системное хранилище сессии недоступно")

    def _key(self, url, account):
        return hashlib.sha256((url + "\n" + account).encode()).hexdigest()

    def get(self, url, account):
        try:
            return self._backend().get_password(self.service, self._key(url, account)) or ""
        except Exception:
            return ""

    def put(self, url, account, token):
        try:
            self._backend().set_password(self.service, self._key(url, account), token)
            return True
        except Exception:
            return False

    def delete(self, url, account):
        try:
            backend = self._backend()
            key = self._key(url, account)
            if backend.get_password(self.service, key):
                backend.delete_password(self.service, key)
        except Exception:
            pass
