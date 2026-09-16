[out:json][timeout:180];
area["ISO3166-2"="RU-MOW"]["admin_level"="4"]->.city;
nwr(area.city)["building"]["addr:housenumber"]["addr:street"];
out center tags;
