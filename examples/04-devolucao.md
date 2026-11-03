# Conversa com o assistente da Empório da Música

### Cliente

Me arrependi da minha compra, posso devolver meu pedido?

### Agente

<details><summary>🔧 check_return({"reason":"arrependimento","channel":null,"received_on":null,"days_since_receipt":null,"purchased_on":null,"days_since_purchase":null,"used":null,"original_packaging":null,"customized":null,"final_sale":null})</summary>

```json
{"decision": "faltam_dados", "rule": "§4.1", "rule_summary": "Compras online: devolução em até 7 dias corridos após o recebimento, sem justificativa. O produto deve estar sem sinais de uso, na embalagem original, com acessórios e manuais. Reembolso na mesma forma de pagamento em até 10 dias úteis; f…
```
</details>

Posso verificar pra você! Para compras online, a política prevê solicitação de devolução em até 7 dias corridos após o recebimento, com o produto sem sinais de uso e na embalagem original, com acessórios e manuais.

Me conta:
- A compra foi online ou na loja?
- Quando você recebeu o produto?
- Ele foi usado?
- Está na embalagem original, com acessórios e manuais?

### Cliente

Comprei pelo site, recebi dia 30/10 e nem tirei da caixa.

### Agente

<details><summary>🔧 check_return({"reason":"arrependimento","channel":"online","received_on":"30/10","days_since_receipt":null,"purchased_on":null,"days_since_purchase":null,"used":false,"original_packaging":true,"customized":null,"final_sale":null})</summary>

```json
{"decision": "pode_solicitar", "rule": "§4.1", "rule_summary": "Compras online: devolução em até 7 dias corridos após o recebimento, sem justificativa. O produto deve estar sem sinais de uso, na embalagem original, com acessórios e manuais. Reembolso na mesma forma de pagamento em até 10 dias úteis;…
```
</details>

Sim, você pode solicitar a devolução! O instrumento deve estar sem sinais de uso, na embalagem original, com acessórios e manuais.

O frete de devolução fica por conta da loja, e o reembolso é feito na mesma forma de pagamento, em até 10 dias úteis.

Para iniciar, fale com a equipe pelo WhatsApp **(67) 3341-4444** ou pelo e-mail **contato@emporiodamusica.com.br**. A loja está fechada agora; a equipe volta a atender na segunda-feira, às 09:00.
