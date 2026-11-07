# Ragquest - Assistente de conhecimento

O Ragquest responde perguntas usando os manuais, diretrizes e POPs da empresa, com busca na internet (com aprovação do usuário) quando a resposta não está nos documentos. A IA roda no servidor da própria empresa, sem custo por uso.

## Instalação (servidor da empresa)

1. Baixe o **Ragquest-Instalador** mais recente em **Releases** (lado direito desta página).
2. Execute o .exe. Se o Windows mostrar "O Windows protegeu o computador", clique em **Mais informações** → **Executar assim mesmo**.
3. Escolha **"Servidor da empresa"** para os funcionários acessarem pela rede (computador e celular). O Windows pede permissão para liberar o firewall: clique em **Sim**.
4. Na primeira abertura, o Ragquest baixa os modelos de IA (3 a 6 GB) e pede a **chave de licença**.
5. Crie a conta de **administrador**. Depois, cadastre os funcionários na aba **Usuários**.
6. Coloque os documentos na pasta **Ragquest - Conhecimento** (em Documentos).

## Acesso dos funcionários

- **Computador:** abrir no navegador o endereço mostrado em Usuários → Acesso dos funcionários.
- **Android:** ler o QR code, tocar em **Baixar o app** e depois em **Abrir no app** (ou instalar o **Ragquest-Android.apk** desta página).
- **iPhone:** ler o QR code e, no Safari, **Compartilhar → Adicionar à Tela de Início**.

Cada funcionário entra com o próprio login e senha. O número de usuários ativos é definido na licença.

## Requisitos do servidor

- Windows 10 ou 11, 64 bits
- 16 GB de RAM recomendado (funciona com 8 GB usando o modelo leve)
- 10 GB livres em disco
- Placa NVIDIA recomendada para respostas mais rápidas

A chave de licença é enviada individualmente. Não compartilhe.

## App Android

O código do app está na pasta `android` e é compilado automaticamente pelo GitHub Actions. A assinatura do APK é feita fora do GitHub.
