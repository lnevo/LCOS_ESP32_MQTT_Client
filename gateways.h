/////////////////////////////////////////
// gateways.h
// @version 1.13
// 8/30/2022
// Copyright 2022 Beagle Bay Inc
/////////////////////////////////////////
#ifndef LCOS_GATEWAYS_H
#define LCOS_GATEWAYS_H

#define MAX_GATEWAYS 2
//////////////////////////////////
// CLASS gateway
//
// type:
//    bit 0 == Sends/readable
//    bit 1 == Receives/writable
//    bit 2 == Binary Messaging
//    type 1 == readable; type 2 == writables; type 3 == bidirectional
//    
//////////////////////////////////
class gateway {
  private:
    bool _enabled;
    byte _type;
    uint16_t _address;
    uint16_t _node;

  public:
   gateway(){
      _type = 0;
      _node = 0;
      _address = 0;
    }
    gateway(byte t, uint16_t a){
      _type = t;
      _address = a;
      _enabled = true;
    }
    gateway(byte t, uint16_t n, uint16_t a){
      _type = t;
      _node = n;
      _address = a;
    }
    boolean isThisGateway(uint16_t a){
      return _address==a;
    }
    uint16_t getAddress(){
      return _address;
    }
    uint16_t getNode(){
      return _node;
    }
    boolean isWritable(){
      return bitRead(_type, 1) == 1;
    }
    boolean isReadable(){
      return bitRead(_type, 0) == 1;
    }
    boolean isBinary(){
      return bitRead(_type, 2) == 1;
    }
    void setAddress(uint16_t a){
      _address = a;
    }
    void setBinary(){
      bitWrite(_type, 2, 1);
    }
    boolean isEnabled() { return _enabled; }
    void enable(){ _enabled = true; }
    void disable(){ _enabled = false; }
};
class gateway_manager{
  private:
    byte count;
    gateway *gateways[MAX_GATEWAYS];

  public:
    gateway_manager(){
      count = 0;
    }
    int getGatewayID(uint16_t addr){
      for(int i = 0; i < count; i++){
        if(gateways[i]->isThisGateway(addr)){
          return i;
        }
      }
      return -1;
    }
    gateway *getGateway(uint16_t node){
      int id = getGatewayID(node);
      if(id > -1) return gateways[id];
      return NULL;
    }
    int register_gateway(byte type, uint16_t addr, uint16_t node){
      if(getGatewayID(addr) == -1 && count < MAX_GATEWAYS){
        gateways[count] = new gateway(type, addr, node);
        return ++count;
      }
      return -1;
    }
    int register_gateway(gateway *g){
      if(count < MAX_GATEWAYS){
        gateways[count] = g;
        return ++count;
      }
      return 0;
    }
    uint16_t getNodeAddress(int gw){
      if(gw > -1 && gw < count){
        return gateways[gw]->getNode();
      }
      return 0;
    }
};

#endif /* LCOS_GATEWAYS_H */
