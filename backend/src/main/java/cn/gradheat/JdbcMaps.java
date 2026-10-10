package cn.gradheat;

import java.util.*;

final class JdbcMaps {
    private JdbcMaps() {}
    static Map<String,Object> lower(Map<String,Object> source) {
        Map<String,Object> result=new LinkedHashMap<>();source.forEach((key,value)->result.put(key.toLowerCase(Locale.ROOT),value));return result;
    }
}
