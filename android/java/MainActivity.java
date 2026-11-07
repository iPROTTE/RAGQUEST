package com.ragquest.app;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * App Ragquest: guarda o endereço do servidor da empresa e abre o Ragquest dele
 * (a tela de login e todo o resto vêm do próprio servidor).
 */
public class MainActivity extends Activity {
    private static final String PREFS = "ragquest", CHAVE = "servidor";
    private static final String CONECTAR = "file:///android_asset/conectar.html";
    private static final String ERRO = "file:///android_asset/erro.html";
    private static final int ARQUIVO = 1;

    private WebView web;
    private ValueCallback<Uri[]> arquivoCb;
    private String ultimoErro = "";

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        web = new WebView(this);
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setUserAgentString(s.getUserAgentString() + " RagquestApp/1");
        web.addJavascriptInterface(new Ponte(), "RagquestApp");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                String srv = servidor();
                if ("file".equals(u.getScheme())) return false;
                if (srv != null && u.toString().startsWith(srv)) return false;
                try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) { }
                return true;                       // links externos abrem no navegador
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame() && !"file".equals(r.getUrl().getScheme())) {
                    ultimoErro = String.valueOf(e.getDescription());
                    v.loadUrl(ERRO);
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams p) {
                if (arquivoCb != null) arquivoCb.onReceiveValue(null);
                arquivoCb = cb;
                try {
                    startActivityForResult(p.createIntent(), ARQUIVO);
                } catch (Exception e) {
                    arquivoCb = null;
                    return false;
                }
                return true;
            }
        });

        if (b != null) web.restoreState(b);
        else tratar(getIntent());
    }

    @Override
    protected void onNewIntent(Intent it) {
        super.onNewIntent(it);
        tratar(it);
    }

    @Override
    protected void onSaveInstanceState(Bundle b) {
        super.onSaveInstanceState(b);
        web.saveState(b);
    }

    private void tratar(Intent it) {
        Uri d = it != null ? it.getData() : null;
        if (d != null && "ragquest".equals(d.getScheme())) {
            String s = d.getQueryParameter("servidor");
            if (s != null && !s.isEmpty()) {
                web.loadUrl(CONECTAR + "#" + Uri.encode(s));
                conectar(s);
                return;
            }
        }
        abrir();
    }

    private void abrir() {
        String s = servidor();
        web.loadUrl(s == null ? CONECTAR : s);
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    private String servidor() {
        return prefs().getString(CHAVE, null);
    }

    /** "192.168.0.10" -> "http://192.168.0.10:8765/" */
    static String normalizar(String s) {
        s = s.trim();
        if (!s.matches("(?i)^https?://.*")) s = "http://" + s;
        Uri u = Uri.parse(s);
        String host = u.getHost();
        if (host == null || host.isEmpty()) return null;
        int porta = u.getPort();
        if (porta == -1 && "http".equalsIgnoreCase(u.getScheme())) porta = 8765;
        return u.getScheme().toLowerCase() + "://" + host + (porta > 0 ? ":" + porta : "") + "/";
    }

    private void js(String codigo) {
        runOnUiThread(() -> web.evaluateJavascript(codigo, null));
    }

    /** Testa se o endereço é um Ragquest e, se for, salva e abre. */
    private void conectar(String endereco) {
        final String url = normalizar(endereco);
        if (url == null) {
            js("erro('Endereço inválido.')");
            return;
        }
        new Thread(() -> {
            String falha;
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(url + "licenca").openConnection();
                c.setConnectTimeout(6000);
                c.setReadTimeout(8000);
                StringBuilder sb = new StringBuilder();
                try (BufferedReader r = new BufferedReader(new InputStreamReader(c.getInputStream(), "UTF-8"))) {
                    String l;
                    while ((l = r.readLine()) != null) sb.append(l);
                }
                if (new JSONObject(sb.toString()).has("valida")) {
                    prefs().edit().putString(CHAVE, url).apply();
                    runOnUiThread(() -> { web.clearHistory(); web.loadUrl(url); });
                    return;
                }
                falha = "Esse endereço não é um servidor Ragquest.";
            } catch (Exception e) {
                falha = "Não consegui falar com " + url + ". Confira o endereço e se o celular está no Wi-Fi da empresa (ou no Tailscale).";
            }
            js("erro(" + JSONObject.quote(falha) + ")");
        }).start();
    }

    /** Funções que as páginas podem chamar (window.RagquestApp). */
    class Ponte {
        @JavascriptInterface public void conectar(String endereco) { MainActivity.this.conectar(endereco); }
        @JavascriptInterface public String servidor() { String s = MainActivity.this.servidor(); return s == null ? "" : s; }
        @JavascriptInterface public String erro() { return ultimoErro; }
        @JavascriptInterface public void tentar() { runOnUiThread(MainActivity.this::abrir); }
        @JavascriptInterface public void trocarServidor() {
            runOnUiThread(() -> {
                String atual = MainActivity.this.servidor();
                prefs().edit().remove(CHAVE).apply();
                web.clearHistory();
                web.loadUrl(CONECTAR + (atual != null ? "#" + Uri.encode(atual) : ""));
            });
        }
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        if (req == ARQUIVO && arquivoCb != null) {
            arquivoCb.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(res, data));
            arquivoCb = null;
            return;
        }
        super.onActivityResult(req, res, data);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
