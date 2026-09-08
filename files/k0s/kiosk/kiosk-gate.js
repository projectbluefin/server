(() => {
  const sessionKey = 'kc-has-session'
  const healthURL = 'http://127.0.0.1:8585/health'
  const gateID = 'kubestellar-kiosk-gate'

  const hasSession = () => {
    try {
      return window.localStorage.getItem(sessionKey) === 'true'
    } catch {
      return false
    }
  }

  const removeGate = () => document.getElementById(gateID)?.remove()

  const showGate = () => {
    if (document.getElementById(gateID)) return

    document.body.insertAdjacentHTML('beforeend', `
      <section id="${gateID}" class="kiosk-gate" role="dialog" aria-modal="true">
        <div class="kiosk-gate__dialog">
          <h1>Connect the kc-agent</h1>
          <p>Monitor your real clusters from this console</p>
          <p>Run agent on machine access kubeconfig</p>
          <code>brew tap kubestellar/tap && brew install kc-agent && kc-agent</code>
          <code>KC_ALLOWED_ORIGINS=${window.location.origin} kc-agent</code>
        </div>
      </section>
    `)
  }

  const updateGate = async () => {
    if (!hasSession()) {
      removeGate()
      return
    }

    try {
      const response = await fetch(healthURL, { credentials: 'omit' })
      if (!response.ok) throw new Error(`kc-agent health: ${response.status}`)
      removeGate()
    } catch {
      showGate()
    }
  }

  document.addEventListener('keydown', (event) => {
    const gate = document.getElementById(gateID)
    if (gate && !gate.contains(event.target)) event.preventDefault()
  }, true)
  window.setInterval(() => void updateGate(), 2_000)
  void updateGate()
})()
