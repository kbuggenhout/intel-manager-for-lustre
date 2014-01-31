mock.factory(function stream() {
  'use strict';

  return jasmine.createSpy('getStream').andCallFake(function getStream() {
    return function Stream () {};
  });
});