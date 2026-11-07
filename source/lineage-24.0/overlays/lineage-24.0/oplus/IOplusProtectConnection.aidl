// SPDX-License-Identifier: Apache-2.0
package com.oplus.app;

// Stock callback order: success=1, error=2, timeout=3; all transactions one-way.
oneway interface IOplusProtectConnection {
    void onSuccess();
    void onError(int errorCode);
    void onTimeout();
}
