/* All demonstration movements are generated independently of the private API. */
(function () {
  "use strict";
  window.PluxeeDemo = {
    createData() {
      const today = new Date(),
        rows = [];
      const shops = [
        ["CAFÉ AURORA", 9.8],
        ["SUPERMERCADO EXEMPLO", 18.6],
        ["BISTRO VERDE", 6.2],
        ["Glovo DEMO", 27.45],
        ["CANTINA CENTRAL", 12.5],
        ["CAFÉ AURORA", 7.9],
        ["BISTRO VERDE", 15.4],
        ["SUPERMERCADO EXEMPLO", 22.1],
        ["CANTINA CENTRAL", 8.7],
        ["Glovo DEMO", 14.2],
        ["BISTRO VERDE", 11.8],
        ["CAFÉ AURORA", 19.6],
      ];
      const days = [2, 4, 7, 10, 12, 15, 18, 20, 23, 25, 27, 29];
      for (let offset = 5; offset >= 0; offset--) {
        const month = new Date(
          today.getFullYear(),
          today.getMonth() - offset,
          1,
        );
        const add = (day, description, amount) => {
          const date = new Date(month.getFullYear(), month.getMonth(), day);
          if (date <= today && date.getMonth() === month.getMonth())
            rows.push({ dateObject: date, description, amount });
        };
        add(
          24,
          "Carregamento de EMPRESA DEMONSTRAÇÃO",
          offset % 2 ? 231.0 : 220.5,
        );
        shops.forEach(([shop, amount], i) =>
          add(days[i], shop, Math.round((-amount - offset * 0.13) * 100) / 100),
        );
      }
      rows.sort((a, b) => a.dateObject - b.dateObject);
      let balance = 150.0;
      const transactions = rows
        .map((row) => {
          balance = Math.round((balance + row.amount) * 100) / 100;
          return {
            date: row.dateObject.toLocaleDateString("pt-PT"),
            description: row.description,
            amount: row.amount,
            balance,
            currency: "EUR",
            effective_date: row.dateObject.toLocaleDateString("pt-PT"),
            raw_description: row.description + ",CIDADE EXEMPLO,PRT",
            is_rejected: false,
          };
        })
        .reverse();
      return {
        success: true,
        demo: true,
        balance: { lunch_pass: balance },
        transactions,
        updated_at: new Date().toISOString(),
      };
    },
  };
})();
