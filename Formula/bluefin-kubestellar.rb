# typed: false
# frozen_string_literal: true

class BluefinKubestellar < Formula
  desc "Single-command launcher and manager for kc-agent (KubeStellar Console)"
  homepage "https://github.com/projectbluefin/server"
  version "0.1.0"
  license "Apache-2.0"

  depends_on "kubestellar/tap/kc-agent"

  def install
    bin.install "files/bin/bluefin-kubestellar" => "bluefin-kubestellar"
  end

  def caveats
    <<~EOS
      To start kc-agent with Bluefin Server console defaults:
        bluefin-kubestellar start

      To check status:
        bluefin-kubestellar status
    EOS
  end

  test do
    system bin/"bluefin-kubestellar", "help"
  end
end
