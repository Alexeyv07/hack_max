[out:json][timeout:180];
area["ISO3166-2"="RU-MOW"]["boundary"="administrative"]["admin_level"="4"]->.moscow;
relation(area.moscow)["boundary"="administrative"]["admin_level"="8"];
out body;
>;
out skel qt;
