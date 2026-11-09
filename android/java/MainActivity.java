package com.ragquest.app;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;

/**
 * App Ragquest: guarda os enderecos do servidor da empresa (rede interna e internet)
 * e abre o que estiver respondendo. Troca sozinho ao sair do Wi-Fi para o 4G e vice-versa.
 * A tela de login e todo o resto vem do proprio servidor.
 */
public class MainActivity extends Activity {
    private static final String PREFS = "ragquest", ATUAL = "servidor", LISTA = "servidores", SESSAO = "sessao";
    private static final String CONECTAR = "file:///android_asset/conectar.html";
    private static final String ABRINDO = "file:///android_asset/abrindo.html";
    private static final String ERRO = "file:///android_asset/erro.html";
    private static final int ARQUIVO = 1;

    private WebView web;
    private ValueCallback<Uri[]> arquivoCb;
    private String ultimoErro = "";
    private volatile boolean procurando = false;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private ConnectivityManager.NetworkCallback redeCb;
    private final Runnable conferir = this::conferirServidorAtual;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        web = new WebView(this);
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setUserAgentString(s.getUserAgentString() + " RagquestApp/2");
        web.addJavascriptInterface(new Ponte(), "RagquestApp");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                if ("file".equals(u.getScheme())) return false;
                if (conhecido(u.toString())) return false;
                try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) { }
                return true;                       // links externos abrem no navegador
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame() && !"file".equals(r.getUrl().getScheme())) {
                    ultimoErro = String.valueOf(e.getDescription());
                    v.loadUrl(ABRINDO);
                    abrir(true);                   // tenta o outro endereco (interno <-> internet)
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

        observarRede();
        if (b != null) web.restoreState(b);
        else tratar(getIntent());
    }

    @Override
    protected void onNewIntent(Intent it) {
        super.onNewIntent(it);
        tratar(it);
    }

    @Override
    protected void onResume() {
        super.onResume();
        ui.removeCallbacks(conferir);
        ui.postDelayed(conferir, 800);
    }

    @Override
    protected void onDestroy() {
        try {
            if (redeCb != null) ((ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE)).unregisterNetworkCallback(redeCb);
        } catch (Exception ignored) { }
        super.onDestroy();
    }

    @Override
    protected void onSaveInstanceState(Bundle b) {
        super.onSaveInstanceState(b);
        web.saveState(b);
    }

    /** Ao trocar de rede (Wi-Fi <-> 4G), confere se o endereco atual ainda responde. */
    private void observarRede() {
        try {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
            redeCb = new ConnectivityManager.NetworkCallback() {
                @Override public void onAvailable(Network n) { agendarConferencia(); }
                @Override public void onLost(Network n) { agendarConferencia(); }
            };
            cm.registerDefaultNetworkCallback(redeCb);
        } catch (Exception ignored) { }
    }

    private void agendarConferencia() {
        ui.removeCallbacks(conferir);
        ui.postDelayed(conferir, 1500);
    }

    private void conferirServidorAtual() {
        final String pagina = web.getUrl();
        if (pagina == null || pagina.startsWith("file:")) return;
        final String atual = servidor();
        if (atual == null) return;
        new Thread(() -> { if (!responde(atual)) abrir(true); }).start();
    }

    private void tratar(Intent it) {
        Uri d = it != null ? it.getData() : null;
        if (d != null && "ragquest".equals(d.getScheme())) {
            String s = d.getQueryParameter("servidor");
            if (s != null && !s.isEmpty()) {
                web.loadUrl(CONECTAR + "#" + Uri.encode(s));
                conectar(s, null);
                return;
            }
        }
        abrir();
    }

    // ------------------------------------------------------------ enderecos guardados
    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    private String servidor() {
        return prefs().getString(ATUAL, null);
    }

    private List<String> servidores() {
        List<String> out = new ArrayList<>();
        try {
            JSONArray a = new JSONArray(prefs().getString(LISTA, "[]"));
            for (int i = 0; i < a.length(); i++) out.add(a.getString(i));
        } catch (Exception ignored) { }
        String s = servidor();
        if (s != null && !out.contains(s)) out.add(0, s);
        return out;
    }

    private synchronized void guardar(String url) {
        if (url == null) return;
        List<String> l = servidores();
        if (!l.contains(url)) l.add(url);
        while (l.size() > 6) l.remove(l.size() - 1);
        prefs().edit().putString(LISTA, new JSONArray(l).toString()).apply();
    }

    private boolean conhecido(String url) {
        for (String s : servidores()) if (url.startsWith(s)) return true;
        return false;
    }

    /** "192.168.0.10" -> "http://192.168.0.10:8765/"   /   "ragquest.empresa.com.br" -> "https://ragquest.empresa.com.br/" */
    static String normalizar(String s) {
        if (s == null) return null;
        s = s.trim();
        if (s.isEmpty()) return null;
        if (!s.matches("(?i)^https?://.*")) {
            boolean ip = s.matches("^[0-9.]+(:\\d+)?(/.*)?$") || s.matches("^[^./:]+(:\\d+)?(/.*)?$");
            s = (ip ? "http://" : "https://") + s;
        }
        Uri u = Uri.parse(s);
        String host = u.getHost();
        if (host == null || host.isEmpty()) return null;
        int porta = u.getPort();
        if (porta == -1 && "http".equalsIgnoreCase(u.getScheme())) porta = 8765;
        return u.getScheme().toLowerCase() + "://" + host + (porta > 0 ? ":" + porta : "") + "/";
    }

    // ------------------------------------------------------------ rede
    private static String baixar(String url, int timeoutMs) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(timeoutMs);
        c.setReadTimeout(timeoutMs + 2000);
        StringBuilder sb = new StringBuilder();
        try (BufferedReader r = new BufferedReader(new InputStreamReader(c.getInputStream(), "UTF-8"))) {
            String l;
            while ((l = r.readLine()) != null) sb.append(l);
        }
        return sb.toString();
    }

    private static boolean responde(String srv) {
        try {
            return new JSONObject(baixar(srv + "licenca", 3500)).has("valida");
        } catch (Exception e) {
            return false;
        }
    }

    /** Pergunta ao servidor quais sao os outros enderecos dele (interno e internet) e guarda. */
    private void aprender(String srv) {
        try {
            JSONObject j = new JSONObject(baixar(srv + "app/enderecos", 5000));
            if (!j.isNull("externo")) guardar(normalizar(j.getString("externo")));
            JSONArray a = j.optJSONArray("internos");
            if (a != null) for (int i = 0; i < a.length() && i < 3; i++) guardar(normalizar(a.getString(i)));
        } catch (Exception ignored) { }
    }

    private void js(String codigo) {
        runOnUiThread(() -> web.evaluateJavascript(codigo, null));
    }

    /** Abre o primeiro endereco guardado que responder (o ultimo que funcionou primeiro). */
    private void abrir() { abrir(false); }

    private void abrir(final boolean forcar) {
        final List<String> lista = servidores();
        if (lista.isEmpty()) {
            runOnUiThread(() -> web.loadUrl(CONECTAR));
            return;
        }
        if (procurando) return;
        procurando = true;
        runOnUiThread(() -> { String p = web.getUrl(); if (p == null || p.startsWith("file:")) web.loadUrl(ABRINDO); });
        new Thread(() -> {
            try {
                for (String srv : lista) {
                    if (responde(srv)) {
                        final boolean trocou = !srv.equals(servidor());
                        prefs().edit().putString(ATUAL, srv).apply();
                        runOnUiThread(() -> {
                            String p = web.getUrl();
                            if (forcar || trocou || p == null || p.startsWith("file:") || !p.startsWith(srv)) {
                                web.clearHistory();
                                web.loadUrl(srv);
                            }
                        });
                        aprender(srv);
                        return;
                    }
                }
                runOnUiThread(() -> web.loadUrl(ERRO));
            } finally {
                procurando = false;
            }
        }).start();
    }

    /** Testa o endereco digitado (e o externo opcional); se for um Ragquest, guarda e abre. */
    private void conectar(String endereco, String externo) {
        final String url = normalizar(endereco);
        final String ext = normalizar(externo);
        if (url == null) {
            js("erro('Endereço inválido.')");
            return;
        }
        new Thread(() -> {
            String alvo = responde(url) ? url : (ext != null && responde(ext) ? ext : null);
            if (alvo != null) {
                guardar(url);
                if (ext != null) guardar(ext);
                prefs().edit().putString(ATUAL, alvo).apply();
                runOnUiThread(() -> { web.clearHistory(); web.loadUrl(alvo); });
                aprender(alvo);
                return;
            }
            js("erro(" + JSONObject.quote("Não consegui falar com " + url
                    + ". Confira o endereço. Fora da empresa, use o endereço de internet (peça ao administrador).") + ")");
        }).start();
    }

    /** Funcoes que as paginas podem chamar (window.RagquestApp). */
    class Ponte {
        @JavascriptInterface public void conectar(String endereco) { MainActivity.this.conectar(endereco, null); }
        @JavascriptInterface public void conectar2(String endereco, String externo) { MainActivity.this.conectar(endereco, externo); }
        @JavascriptInterface public String servidor() { String s = MainActivity.this.servidor(); return s == null ? "" : s; }
        @JavascriptInterface public String servidores() { return new JSONArray(MainActivity.this.servidores()).toString(); }
        @JavascriptInterface public String erro() { return ultimoErro; }
        @JavascriptInterface public void tentar() { abrir(); }
        /** A sessao (login) vale para todos os enderecos do mesmo servidor. */
        @JavascriptInterface public String sessao() { return prefs().getString(SESSAO, ""); }
        @JavascriptInterface public void guardarSessao(String t) {
            if (t == null || t.isEmpty()) prefs().edit().remove(SESSAO).apply();
            else prefs().edit().putString(SESSAO, t).apply();
        }
        @JavascriptInterface public void trocarServidor() {
            runOnUiThread(() -> {
                String atual = MainActivity.this.servidor();
                prefs().edit().remove(ATUAL).remove(LISTA).remove(SESSAO).apply();
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
